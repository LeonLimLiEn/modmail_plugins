from __future__ import annotations

from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union, TYPE_CHECKING

import discord
from discord import ButtonStyle, Interaction, TextStyle
from discord.ext import commands
from discord.ui import Button, Modal, TextInput, View
from discord.utils import MISSING

from .utils import duration_syntax, time_converter


if TYPE_CHECKING:
    from ..giveaway import Giveaway
    from .sessions import GiveawaySession

    ButtonCallbackT = Callable[[Union[Interaction, Any]], Awaitable]


_short_length = 256
_long_length = 4000
_field_value_length = 2048

GIFT = "\U0001F381"
TADA = "\U0001F389"
LOCK = "\U0001F512"


# ---------------------------------------------------------------------------
# Setup view (admin uses this to configure the giveaway before posting)
# ---------------------------------------------------------------------------


class GiveawayTextInput(TextInput):
    def __init__(self, name: str, **kwargs):
        self.name: str = name
        super().__init__(**kwargs)


class GiveawayModal(Modal):
    children: List[GiveawayTextInput]

    def __init__(self, view: "GiveawaySetupView"):
        super().__init__(title="Giveaway")
        self.view = view
        self.view.modals.append(self)
        for key, value in self.view.input_map.items():
            self.add_item(GiveawayTextInput(key, **value))

    async def on_submit(self, interaction: Interaction) -> None:
        for child in self.children:
            self.view.input_map[child.name]["default"] = child.value
        await interaction.response.defer()
        self.stop()
        await self.view.on_modal_submit(interaction)


class _SetupButton(Button["GiveawaySetupView"]):
    def __init__(
        self,
        label: str,
        *,
        style: ButtonStyle = ButtonStyle.blurple,
        callback: "ButtonCallbackT" = MISSING,
    ):
        super().__init__(label=label, style=style)
        self.callback_override: "ButtonCallbackT" = callback

    async def callback(self, interaction: Interaction):
        assert self.view is not None
        await self.callback_override(interaction)


class GiveawaySetupView(View):
    """
    The control panel the admin uses to fill in giveaway details before
    posting it. This is *not* the entry view — entry uses a persistent
    `EntryView` registered against the bot.
    """

    children: List[_SetupButton]

    def __init__(self, ctx: commands.Context, *, timeout: float = 600.0):
        super().__init__(timeout=timeout)
        self.ctx: commands.Context = ctx
        self.cog: "Giveaway" = ctx.cog
        self.user: discord.Member = ctx.author
        self.message: discord.Message = MISSING
        self.giveaway_ready: bool = False
        self.giveaway_end: float = MISSING
        self.giveaway_winners: int = MISSING
        self.giveaway_prize: str = MISSING
        self.required_role_id: Optional[int] = None
        self.bonus_entries: Dict[int, int] = {}
        self.embed: discord.Embed = MISSING
        self._underlying_modals: List[GiveawayModal] = []

        self.input_map: Dict[str, Any] = {
            "content": {
                "label": "Content (optional pings)",
                "style": TextStyle.long,
                "max_length": _long_length,
                "required": False,
            },
            "prize": {
                "label": "Giveaway prize",
                "max_length": _field_value_length,
            },
            "winners": {
                "label": "Winners count (1-50)",
                "max_length": 2,
            },
            "duration": {
                "label": "Duration (e.g. 1h, 2d, 30m)",
                "max_length": _short_length,
            },
            "required_role": {
                "label": "Required role ID (optional)",
                "max_length": 20,
                "required": False,
            },
        }
        self.ret_buttons: Dict[str, Any] = {
            "send": (ButtonStyle.green, self._action_done),
            "edit": (ButtonStyle.grey, self._action_edit),
            "preview": (ButtonStyle.grey, self._action_preview),
            "cancel": (ButtonStyle.red, self._action_cancel),
        }

        self._generate_buttons()
        self.refresh()

    @property
    def modals(self) -> List[GiveawayModal]:
        return self._underlying_modals

    def _generate_buttons(self) -> None:
        for label, item in self.ret_buttons.items():
            self.add_item(_SetupButton(label.title(), style=item[0], callback=item[1]))

    def refresh(self) -> None:
        for child in self.children:
            if child.label.lower() in ("send", "preview"):
                child.disabled = not self.giveaway_ready

    async def update_view(self) -> None:
        self.refresh()
        await self.message.edit(view=self)

    async def _action_done(self, interaction: Interaction) -> None:
        await interaction.response.defer()
        self.disable_and_stop()
        await self.message.edit(view=self)

    async def _action_edit(self, interaction: Interaction) -> None:
        modal = GiveawayModal(self)
        await interaction.response.send_modal(modal)
        await modal.wait()

    async def _action_preview(self, interaction: Interaction) -> None:
        try:
            await interaction.response.send_message(ephemeral=True, **self.send_params())
        except discord.HTTPException as exc:
            error = f"**Error:**\n```py\n{type(exc).__name__}: {str(exc)}\n```"
            await interaction.response.send_message(error, ephemeral=True)

    async def _action_cancel(self, interaction: Interaction) -> None:
        self.giveaway_ready = False
        self.disable_and_stop()
        await interaction.response.edit_message(view=self)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if self.user.id == interaction.user.id:
            return True
        await interaction.response.send_message(
            "This panel cannot be controlled by you!", ephemeral=True
        )
        return False

    async def on_modal_submit(self, interaction: Interaction) -> None:
        errors: List[str] = []
        self.giveaway_prize = self.input_map["prize"].get("default")

        winners = self.input_map["winners"].get("default")
        try:
            winners = int(winners)
        except (TypeError, ValueError):
            errors.append("Unable to convert giveaway winners to a number.")
        else:
            if not 1 <= winners <= 50:
                errors.append("Giveaway can only be held with 1 up to 50 winners.")
            else:
                self.giveaway_winners = winners

        duration = self.input_map["duration"].get("default")
        try:
            converted = await time_converter(self.ctx, duration, now=discord.utils.utcnow())
        except (commands.BadArgument, commands.CommandError):
            errors.append(
                "Failed to parse duration. Please use the following syntax.\n\n"
                f"{duration_syntax}"
            )
        else:
            if converted.dt.timestamp() - converted.now.timestamp() <= 0:
                errors.append("Invalid duration provided.")
            else:
                self.giveaway_end = converted.dt.timestamp()

        role_raw = self.input_map.get("required_role", {}).get("default")
        if role_raw:
            try:
                rid = int(role_raw.strip().lstrip("<@&").rstrip(">"))
            except (TypeError, ValueError):
                errors.append("Required role must be a valid role ID or mention.")
            else:
                role = self.ctx.guild.get_role(rid) if self.ctx.guild else None
                if role is None:
                    errors.append("Required role not found in this server.")
                else:
                    self.required_role_id = role.id

        if errors:
            self.giveaway_ready = False
            for error in errors:
                await interaction.followup.send(error, ephemeral=True)
        else:
            self.embed = self.create_embed()
            self.giveaway_ready = True
        await self.update_view()

    def send_params(self) -> Dict[str, Any]:
        params = {"embed": self.embed}
        content = self.input_map["content"].get("default")
        if content:
            params["content"] = content
        return params

    def create_embed(self) -> discord.Embed:
        winners = self.giveaway_winners
        end_dt = datetime.fromtimestamp(self.giveaway_end)

        embed = discord.Embed(title=self.cog.giveaway_title, colour=0x2ECC71)
        embed.set_author(**self.cog.author_data("system", extra="giveaway"))
        embed.description = (
            f"{TADA} Click **Enter** below to join the giveaway!\n"
            f"Use **Leave** to withdraw. Click **Participants** to see how many have entered."
        )
        embed.add_field(name=f"{GIFT} Prize", value=self.giveaway_prize, inline=False)
        embed.add_field(name="Hosted by", value=self.ctx.author.mention, inline=True)
        embed.add_field(name="Entries", value="**0**", inline=True)
        embed.add_field(
            name="Ends",
            value=(
                f"{discord.utils.format_dt(end_dt, 'R')}\n"
                f"({discord.utils.format_dt(end_dt, 'F')})"
            ),
            inline=False,
        )
        if self.required_role_id:
            embed.add_field(
                name=f"{LOCK} Required role",
                value=f"<@&{self.required_role_id}>",
                inline=False,
            )
        embed.set_footer(text=f"{winners} winner{'s' if winners > 1 else ''} • Ends")
        embed.timestamp = end_dt
        return embed

    def disable_and_stop(self) -> None:
        for child in self.children:
            child.disabled = True
        for modal in self.modals:
            if modal.is_dispatching() or not modal.is_finished():
                modal.stop()
        if not self.is_finished():
            self.stop()

    async def on_timeout(self) -> None:
        self.giveaway_ready = False
        self.disable_and_stop()
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass


# ---------------------------------------------------------------------------
# Persistent entry view — the buttons attached to the live giveaway message
# ---------------------------------------------------------------------------


CUSTOM_ID_ENTER = "giveaway:enter"
CUSTOM_ID_LEAVE = "giveaway:leave"
CUSTOM_ID_PARTICIPANTS = "giveaway:participants"


class EntryView(View):
    """
    Persistent view registered with the bot so the buttons survive restarts.

    The view itself doesn't store any state — it routes clicks to the cog,
    which looks up the active session by message ID. This is what makes
    entries reliable: every click resolves through the cog's authoritative
    session map rather than depending on Discord reaction state.
    """

    def __init__(self, cog: "Giveaway"):
        super().__init__(timeout=None)
        self.cog: "Giveaway" = cog

    @discord.ui.button(
        label="Enter",
        style=ButtonStyle.success,
        emoji=TADA,
        custom_id=CUSTOM_ID_ENTER,
    )
    async def enter(self, interaction: Interaction, button: Button) -> None:
        await self.cog.handle_enter_click(interaction)

    @discord.ui.button(
        label="Leave",
        style=ButtonStyle.danger,
        custom_id=CUSTOM_ID_LEAVE,
    )
    async def leave(self, interaction: Interaction, button: Button) -> None:
        await self.cog.handle_leave_click(interaction)

    @discord.ui.button(
        label="Participants",
        style=ButtonStyle.secondary,
        custom_id=CUSTOM_ID_PARTICIPANTS,
    )
    async def participants(self, interaction: Interaction, button: Button) -> None:
        await self.cog.handle_participants_click(interaction)


def disabled_entry_view() -> View:
    """Return a view with the same three buttons but greyed out, used after the giveaway ends."""
    view = View(timeout=None)
    view.add_item(
        Button(label="Enter", style=ButtonStyle.success, emoji=TADA, disabled=True, custom_id=CUSTOM_ID_ENTER)
    )
    view.add_item(
        Button(label="Leave", style=ButtonStyle.danger, disabled=True, custom_id=CUSTOM_ID_LEAVE)
    )
    view.add_item(
        Button(
            label="Participants",
            style=ButtonStyle.secondary,
            disabled=True,
            custom_id=CUSTOM_ID_PARTICIPANTS,
        )
    )
    return view
        
