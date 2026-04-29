from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

import discord
import yarl

from discord.ext import commands

from core import checks
from core.models import getLogger, PermissionLevel

from .core.checks import can_execute_giveaway
from .core.sessions import GiveawaySession
from .core.utils import duration_syntax, format_time_remaining, time_converter
from .core.views import (
    EntryView,
    GiveawaySetupView,
    disabled_entry_view,
    GIFT,
    LOCK,
    TADA,
)


if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection
    from bot import ModmailBot


info_json = Path(__file__).parent.resolve() / "info.json"
with open(info_json, encoding="utf-8") as f:
    __plugin_info__ = json.loads(f.read())

__version__ = __plugin_info__["version"]
__description__ = "\n".join(__plugin_info__["description"]).format(__version__)


logger = getLogger(__name__)

BASE_URL = "https://discordapp.com"
MAX_ACTIVE = 25


class Giveaway(commands.Cog):
    __doc__ = __description__

    def __init__(self, bot: "ModmailBot"):
        self.bot: "ModmailBot" = bot
        self.db: "AsyncIOMotorCollection" = bot.api.get_plugin_partition(self)
        self.active_giveaways: List[GiveawaySession] = []
        self._db_lock = asyncio.Lock()
        self._entry_view: Optional[EntryView] = None

    # ------------------------------------------------------------- lifecycle

    async def cog_load(self) -> None:
        # Register the persistent entry view so button clicks survive restarts.
        self._entry_view = EntryView(self)
        self.bot.add_view(self._entry_view)
        self.bot.loop.create_task(self.populate_from_db())

    async def cog_unload(self) -> None:
        for session in self.active_giveaways:
            session.force_stop()
        if self._entry_view is not None:
            self._entry_view.stop()

    async def populate_from_db(self) -> None:
        await self.bot.wait_for_connected()

        config = await self.db.find_one({"_id": "config"})
        if config is None:
            await self.db.find_one_and_update(
                {"_id": "config"},
                {"$set": {"giveaways": {}}},
                upsert=True,
            )
            return

        giveaways = config.get("giveaways", {})
        for message_id, giveaway in giveaways.items():
            if self._get_giveaway_session(int(message_id)) is not None:
                continue
            session = GiveawaySession.start(self, giveaway)
            self.active_giveaways.append(session)

    async def _update_db(self) -> None:
        async with self._db_lock:
            active = {}
            for session in self.active_giveaways:
                if session.done:
                    continue
                active[str(session.id)] = session.serializable()
            await self.db.find_one_and_update(
                {"_id": "config"},
                {"$set": {"giveaways": active}},
                upsert=True,
            )

    # --------------------------------------------------------------- helpers

    def author_data(
        self, message_type: str = "other", *, extra: Optional[str] = None, **kwargs
    ) -> Dict[str, str]:
        url = yarl.URL(f"{BASE_URL}/users/{self.bot.user.id}")
        kwargs["type"] = message_type
        url = url.update_query(**kwargs)
        if extra:
            url = url.with_fragment(extra)
        return {
            "name": self.bot.user.name,
            "icon_url": str(self.bot.user.display_avatar),
            "url": str(url),
        }

    def is_giveaway_embed(self, embed: discord.Embed) -> bool:
        if not embed.title or embed.title != self.giveaway_title:
            return False
        url = getattr(embed.author, "url", "") or ""
        if not url:
            return False
        url = yarl.URL(url)
        if url.query.get("type") != "system" or url.fragment != "giveaway":
            return False
        path_re = re.compile(r"^/users/(?P<id>\d{17,21})(.+)?")
        match = path_re.match(url.path)
        if match is None:
            return False
        try:
            return int(match.group("id")) == self.bot.user.id
        except (TypeError, ValueError):
            return False

    def _get_giveaway_session(self, message_id: int) -> Optional[GiveawaySession]:
        return next(
            (s for s in self.active_giveaways if s.id == message_id),
            None,
        )

    @property
    def giveaway_title(self) -> str:
        return "Giveaway"

    @property
    def giveaway_emoji(self) -> str:
        return TADA

    # ----------------------------------------------------- button handlers

    async def handle_enter_click(self, interaction: discord.Interaction) -> None:
        session = self._get_giveaway_session(interaction.message.id)
        if session is None or session.done:
            await interaction.response.send_message(
                "This giveaway is no longer accepting entries.", ephemeral=True
            )
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "You must be in the server to enter.", ephemeral=True
            )
            return

        if member.bot:
            await interaction.response.send_message(
                "Bots can't enter giveaways.", ephemeral=True
            )
            return

        if session.required_role_id and not any(
            r.id == session.required_role_id for r in member.roles
        ):
            await interaction.response.send_message(
                f"You need <@&{session.required_role_id}> to enter this giveaway.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        if member.id in session.entrants:
            await interaction.response.send_message(
                f"{TADA} You're already entered! You have **{session.total_entries_for(member)}** "
                f"entr{'ies' if session.total_entries_for(member) != 1 else 'y'}.",
                ephemeral=True,
            )
            return

        session.entrants.add(member.id)
        await self._update_db()
        await self._update_entries_field(session)

        tickets = session.total_entries_for(member)
        await interaction.response.send_message(
            f"{TADA} You're in! You have **{tickets}** entr{'ies' if tickets != 1 else 'y'}. "
            f"Good luck!",
            ephemeral=True,
        )

    async def handle_leave_click(self, interaction: discord.Interaction) -> None:
        session = self._get_giveaway_session(interaction.message.id)
        if session is None or session.done:
            await interaction.response.send_message(
                "This giveaway is no longer active.", ephemeral=True
            )
            return

        if interaction.user.id not in session.entrants:
            await interaction.response.send_message(
                "You weren't entered.", ephemeral=True
            )
            return

        session.entrants.discard(interaction.user.id)
        await self._update_db()
        await self._update_entries_field(session)
        await interaction.response.send_message(
            "You've withdrawn from this giveaway.", ephemeral=True
        )

    async def handle_participants_click(self, interaction: discord.Interaction) -> None:
        session = self._get_giveaway_session(interaction.message.id)
        if session is None:
            await interaction.response.send_message(
                "Couldn't find this giveaway.", ephemeral=True
            )
            return

        count = len(session.entrants)
        you_in = interaction.user.id in session.entrants
        bonus_lines = ""
        if session.bonus_entries:
            bonus_lines = "\n\n**Bonus entries:**\n" + "\n".join(
                f"<@&{rid}>: +{extra}" for rid, extra in session.bonus_entries.items()
            )

        msg = (
            f"**Entries:** {count}\n"
            f"**Status:** {'You are entered' if you_in else 'You are not entered'}\n"
            f"{session.render_progress()}"
            f"{bonus_lines}"
        )
        await interaction.response.send_message(
            msg,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _update_entries_field(self, session: GiveawaySession) -> None:
        """Best-effort refresh of the 'Entries' field on the live embed."""
        if session.message is None:
            return
        if not session.message.embeds:
            return
        embed = session.message.embeds[0]
        for idx, field in enumerate(embed.fields):
            if field.name == "Entries":
                embed.set_field_at(idx, name="Entries", value=f"**{len(session.entrants)}**", inline=True)
                break
        try:
            await session.message.edit(embed=embed)
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------- commands

    @commands.group(aliases=["gaway"], invoke_without_command=True)
    @commands.guild_only()
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def giveaway(self, ctx: commands.Context):
        """
        Create / Stop / Manage giveaways.

        __**Notes:**__
        - Bot needs `View Channel`, `Send Messages`, `Read Message History`, `Embed Links`.
        - Up to 25 giveaways may run at once.
        """
        await ctx.send_help(ctx.command)

    @giveaway.command(aliases=["create"])
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def start(self, ctx: commands.Context, channel: discord.TextChannel):
        """
        Start a giveaway with interactive buttons.

        `channel` may be a channel ID, mention, or name.
        """
        if not can_execute_giveaway(ctx, channel):
            ch_text = "this channel"
            if ctx.channel != channel:
                ch_text += f" and {channel.mention}"
            raise commands.BadArgument(
                "Need `Send Messages`, `Read Message History`, `Embed Links`, "
                f"and `View Channel` permissions in {ch_text}."
            )
        if len(self.active_giveaways) >= MAX_ACTIVE:
            raise commands.BadArgument(f"Only {MAX_ACTIVE} active giveaways are allowed at a time.")

        view = GiveawaySetupView(ctx)
        embed = discord.Embed(
            title="Giveaway Settings",
            color=self.bot.main_color,
            description=(
                f"Giveaway will be posted in {channel.mention}.\n"
                "Click **Edit** to set values.\n\n"
                "__**Available fields:**__\n"
                "- **Content** : optional pings (`<@id>` for users, `<@&id>` for roles, or `@here`/`@everyone`).\n"
                "- **Prize** : Giveaway prize.\n"
                "- **Winners count** : Integer 1-50.\n"
                "- **Duration** : See syntax below.\n"
                "- **Required role ID** : Optional. Only members with this role may enter.\n"
            ),
        )
        embed.add_field(name="Duration syntax", value=duration_syntax)
        embed.set_footer(text="This panel will time out after 10 minutes.")
        view.message = await ctx.send(embed=embed, view=view)
        await view.wait()

        if not view.giveaway_ready:
            return

        message = await channel.send(**view.send_params(), view=EntryView(self))
        await ctx.send(f"Done. Giveaway has been posted in {channel.mention}.")

        data = {
            "item": view.giveaway_prize,
            "winners": view.giveaway_winners,
            "time": view.giveaway_end,
            "guild": channel.guild.id,
            "channel": channel.id,
            "message": message.id,
            "host": ctx.author.id,
            "required_role": view.required_role_id,
            "bonus_entries": view.bonus_entries,
            "dm_winners": True,
            "entrants": [],
            "created_at": discord.utils.utcnow().timestamp(),
        }
        session = GiveawaySession.start(self, data)
        session.message = message
        self.active_giveaways.append(session)
        await self._update_db()

    @giveaway.command(aliases=["rroll"])
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def reroll(
        self,
        ctx: commands.Context,
        message_id: int,
        winners_count: int = 1,
    ):
        """
        Reroll an ended giveaway.

        **Usage:**
        `{prefix}giveaway reroll <message_id> [winners_count=1]`
        """
        if self._get_giveaway_session(message_id) is not None:
            raise commands.BadArgument("You can't reroll an active giveaway.")

        try:
            message = await ctx.channel.fetch_message(message_id)
        except discord.Forbidden:
            raise commands.BadArgument("No permission to read message history.")
        except discord.NotFound:
            raise commands.BadArgument("Message not found in this channel.")

        if message.author.id != self.bot.user.id:
            raise commands.BadArgument("That message wasn't from me.")
        if not message.embeds or not self.is_giveaway_embed(message.embeds[0]):
            raise commands.BadArgument("That message isn't a giveaway.")

        # Look up the historical entrants from the DB (kept after end).
        config = await self.db.find_one({"_id": "config"}) or {}
        history = config.get("history", {}).get(str(message_id))
        if not history:
            raise commands.BadArgument(
                "No historical entrants stored for that giveaway. "
                "Reroll only works for giveaways finalized by this version of the plugin."
            )

        entrants = [int(uid) for uid in history.get("entrants", [])]
        if not entrants:
            raise commands.BadArgument("Nobody eligible entered that giveaway.")

        guild = ctx.guild
        eligible = [
            uid for uid in entrants
            if (m := guild.get_member(uid)) is not None and not m.bot
        ]
        if not eligible:
            raise commands.BadArgument("No eligible entrants are still in the server.")

        import random
        random.shuffle(eligible)
        winners = eligible[:max(1, winners_count)]

        mentions = " ".join(f"<@{uid}>" for uid in winners)
        await ctx.send(
            f"{TADA} Rerolled! Congratulations {mentions}, you won **{history.get('item', 'the prize')}**!",
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    @giveaway.command(aliases=["stop"])
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def cancel(self, ctx: commands.Context, message_id: int):
        """
        Stop an active giveaway without picking a winner.

        **Usage:** `{prefix}giveaway cancel <message_id>`
        """
        session = self._get_giveaway_session(message_id)
        if session is None:
            raise commands.BadArgument("Unable to find an active giveaway with that ID.")

        channel = self.bot.get_channel(session.channel_id)
        try:
            message = await channel.fetch_message(message_id)
        except (discord.Forbidden, discord.NotFound):
            message = None

        if message and message.embeds:
            embed = message.embeds[0]
            embed.description = "The giveaway has been cancelled."
            embed.colour = 0x95A5A6
            try:
                await message.edit(embed=embed, view=disabled_entry_view())
            except discord.HTTPException:
                pass

        session.force_stop()
        if session in self.active_giveaways:
            self.active_giveaways.remove(session)
        await self._update_db()
        await ctx.send(f"Giveaway `{message_id}` is now cancelled.")

    @giveaway.command(name="end")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def end_now(self, ctx: commands.Context, message_id: int):
        """End a giveaway right now and pick winners immediately."""
        session = self._get_giveaway_session(message_id)
        if session is None:
            raise commands.BadArgument("No active giveaway with that ID.")
        session.ends = discord.utils.utcnow().timestamp()
        if session._task and not session._task.done():
            session._task.cancel()
        # Kick off finalize directly.
        self.bot.loop.create_task(session._finalize())
        await ctx.send(f"Ending giveaway `{message_id}` now.")

    @giveaway.command(name="pause")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def pause_cmd(self, ctx: commands.Context, message_id: int):
        """Pause an active giveaway. The remaining time is preserved."""
        session = self._get_giveaway_session(message_id)
        if session is None:
            raise commands.BadArgument("No active giveaway with that ID.")
        if session.paused:
            raise commands.BadArgument("That giveaway is already paused.")
        await session.pause()
        await ctx.send(
            f"Paused giveaway `{message_id}` with "
            f"**{format_time_remaining(session.pause_remaining or 0)}** remaining."
        )

    @giveaway.command(name="resume")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def resume_cmd(self, ctx: commands.Context, message_id: int):
        """Resume a paused giveaway."""
        session = self._get_giveaway_session(message_id)
        if session is None:
            raise commands.BadArgument("No active giveaway with that ID.")
        if not session.paused:
            raise commands.BadArgument("That giveaway is not paused.")
        await session.resume()
        await ctx.send(f"Resumed giveaway `{message_id}`.")

    @giveaway.command(name="edit")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def edit_cmd(
        self,
        ctx: commands.Context,
        message_id: int,
        field: str,
        *,
        value: str,
    ):
        """
        Edit a running giveaway.

        **Fields:** `prize`, `winners`, `duration` (extends/sets remaining time).

        **Usage:** `{prefix}giveaway edit <message_id> <field> <value>`
        """
        session = self._get_giveaway_session(message_id)
        if session is None:
            raise commands.BadArgument("No active giveaway with that ID.")

        field = field.lower().strip()
        if field == "prize":
            session.giveaway_item = value
        elif field == "winners":
            try:
                n = int(value)
            except ValueError:
                raise commands.BadArgument("Winners must be a number.")
            if not 1 <= n <= 50:
                raise commands.BadArgument("Winners must be between 1 and 50.")
            session.winners_count = n
        elif field == "duration":
            try:
                converted = await time_converter(ctx, value, now=discord.utils.utcnow())
            except (commands.BadArgument, commands.CommandError):
                raise commands.BadArgument(f"Bad duration. Try: `{duration_syntax}`")
            session.ends = converted.dt.timestamp()
            # Restart the task so the new end time takes effect.
            if session._task and not session._task.done():
                session._task.cancel()
            session._task = self.bot.loop.create_task(session._run())
            session._task.add_done_callback(session._task_done)
        else:
            raise commands.BadArgument("Field must be one of: prize, winners, duration.")

        await self._update_db()
        await self._refresh_live_embed(session)
        await ctx.send(f"Updated `{field}` fo
