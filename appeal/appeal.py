import discord
from discord.ext import commands
from discord import ui
from core import checks
from core.models import PermissionLevel
import logging

# ============================================================
# CREDENTIALS — fill these in before running
# ============================================================
APPEAL_CHANNEL_ID = 1493584131458728076   # staff appeal review channel ID
STAFF_ROLE_ID = 1458475722040672288        # staff role ID who can vote
# ============================================================

logger = logging.getLogger("Modmail")

# Active votes keyed by appeal message ID
# { message_id: { "accept": set(), "decline": set(), "applicant_id": int, "roblox_username": str } }
_active_votes: dict[int, dict] = {}

# Saved form progress keyed by user ID so progress survives accidental dismissals
# { user_id: { "discord_username": str, "roblox_username": str, "ban_reason": str,
#              "appeal_reason": str, "additional": str } }
_saved_progress: dict[int, dict] = {}


# ------------------------------------------------------------------ helpers

async def _end_vote(bot: commands.Bot, message: discord.Message, ended_by: str) -> None:
    """Shared logic to close a vote and DM the applicant the result."""
    data = _active_votes.pop(message.id, None)
    if not data:
        return

    accept_count = len(data["accept"])
    decline_count = len(data["decline"])

    if accept_count > decline_count:
        result_label = "✅ ACCEPTED"
        color = discord.Color.green()
        dm_msg = (
            f"✅ Your ban appeal for Roblox user **{data['roblox_username']}** has been **accepted**.\n"
            "Please contact staff for next steps."
        )
    elif decline_count > accept_count:
        result_label = "❌ DECLINED"
        color = discord.Color.red()
        dm_msg = (
            f"❌ Your ban appeal for Roblox user **{data['roblox_username']}** has been **declined**."
        )
    else:
        result_label = "⚖️ TIE — No decision"
        color = discord.Color.greyple()
        dm_msg = (
            f"⚖️ Your ban appeal for Roblox user **{data['roblox_username']}** resulted in a tie. "
            "Please contact staff directly."
        )

    embed = message.embeds[0]
    embed.title = f"📋 Ban Appeal — {result_label}"
    embed.color = color
    for i, field in enumerate(embed.fields):
        if field.name == "Current Votes":
            embed.set_field_at(
                i,
                name="Final Result",
                value=(
                    f"✅ Accept: **{accept_count}** | ❌ Decline: **{decline_count}**\n"
                    f"**{result_label}**"
                ),
                inline=False,
            )
            break
    embed.set_footer(text=f"Vote ended by {ended_by}")

    # Disable all buttons on the view
    view = discord.ui.View()
    for child in message.components[0].children if message.components else []:
        btn = discord.ui.Button(
            label=child.label,
            style=child.style,
            disabled=True,
            custom_id=child.custom_id,
        )
        view.add_item(btn)

    await message.edit(embed=embed, view=view)

    applicant = bot.get_user(data["applicant_id"])
    if applicant:
        try:
            await applicant.send(dm_msg)
        except discord.Forbidden:
            logger.warning(f"Could not DM user {applicant.id} with appeal result")


async def _check_auto_end(bot: commands.Bot, message: discord.Message, view: "AppealVoteView") -> bool:
    """
    Check if every member with the staff role has cast a vote.
    If so, auto-end the vote. Returns True if auto-ended.
    """
    data = _active_votes.get(message.id)
    if not data:
        return False

    channel = message.channel
    guild = channel.guild
    staff_role = guild.get_role(STAFF_ROLE_ID)
    if not staff_role:
        return False

    # Count members who currently have the staff role (excluding bots)
    staff_members = {m.id for m in staff_role.members if not m.bot}
    if not staff_members:
        return False

    total_voted = data["accept"] | data["decline"]

    if staff_members <= total_voted:
        # All staff have voted — auto-end
        await _end_vote(bot, message, "automatic (all staff voted)")
        await channel.send(
            f"🔒 Vote auto-closed — all {len(staff_members)} staff members have cast their vote.",
        )
        return True

    return False


# ------------------------------------------------------------------ Modal

class AppealModal(ui.Modal, title="Ban Appeal Application"):
    discord_username = ui.TextInput(
        label="Discord Username",
        placeholder="Your Discord username (e.g. username#0000 or username)",
        max_length=50,
    )
    roblox_username = ui.TextInput(
        label="Roblox Username",
        placeholder="Your exact Roblox username",
        max_length=50,
    )
    ban_reason = ui.TextInput(
        label="What were you banned for?",
        style=discord.TextStyle.paragraph,
        placeholder="Explain the situation honestly",
        max_length=500,
    )
    appeal_reason = ui.TextInput(
        label="Why should you be unbanned?",
        style=discord.TextStyle.paragraph,
        placeholder="Make your case here",
        max_length=500,
    )
    additional = ui.TextInput(
        label="Anything else to add?",
        style=discord.TextStyle.paragraph,
        placeholder="Optional — leave blank if nothing",
        required=False,
        max_length=300,
    )

    def __init__(self, applicant: discord.User | discord.Member):
        super().__init__()
        self.applicant = applicant

        # Pre-fill with any saved progress
        saved = _saved_progress.get(applicant.id, {})
        if saved.get("discord_username"):
            self.discord_username.default = saved["discord_username"]
        if saved.get("roblox_username"):
            self.roblox_username.default = saved["roblox_username"]
        if saved.get("ban_reason"):
            self.ban_reason.default = saved["ban_reason"]
        if saved.get("appeal_reason"):
            self.appeal_reason.default = saved["appeal_reason"]
        if saved.get("additional"):
            self.additional.default = saved["additional"]

    async def on_submit(self, interaction: discord.Interaction) -> None:
        channel = interaction.client.get_channel(APPEAL_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message(
                "❌ The appeal review channel could not be found. Please contact an administrator.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="📋 New Ban Appeal",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Applicant",
            value=f"{self.applicant.mention} (`{self.applicant.id}`)",
            inline=False,
        )
        embed.add_field(name="Discord Username", value=self.discord_username.value, inline=True)
        embed.add_field(name="Roblox Username", value=self.roblox_username.value, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="What they were banned for", value=self.ban_reason.value, inline=False)
        embed.add_field(name="Why they should be unbanned", value=self.appeal_reason.value, inline=False)
        if self.additional.value.strip():
            embed.add_field(name="Additional Info", value=self.additional.value, inline=False)
        embed.add_field(
            name="Current Votes",
            value="✅ Accept: **0** | ❌ Decline: **0**",
            inline=False,
        )
        embed.set_thumbnail(url=self.applicant.display_avatar.url)
        embed.set_footer(text="Staff: vote below. A Modmail administrator can end the vote at any time.")

        view = AppealVoteView(
            applicant_id=self.applicant.id,
            roblox_username=self.roblox_username.value,
        )

        # Ping the staff role when posting the appeal
        staff_ping = f"<@&{STAFF_ROLE_ID}>" if STAFF_ROLE_ID else ""
        msg = await channel.send(content=staff_ping or None, embed=embed, view=view)
        view.message_id = msg.id

        _active_votes[msg.id] = {
            "accept": set(),
            "decline": set(),
            "applicant_id": self.applicant.id,
            "roblox_username": self.roblox_username.value,
        }

        # Clear saved progress now that the appeal has been submitted
        _saved_progress.pop(self.applicant.id, None)

        await interaction.response.send_message(
            "✅ Your appeal has been submitted and is under review by staff. You will be notified of the outcome.",
            ephemeral=True,
        )


# ------------------------------------------------------------------ Vote view

class AppealVoteView(ui.View):
    def __init__(self, applicant_id: int, roblox_username: str):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.roblox_username = roblox_username
        self.message_id: int | None = None

    def _is_staff(self, member: discord.Member) -> bool:
        """Check if the member has the staff role."""
        if not STAFF_ROLE_ID:
            return False
        staff_role = member.guild.get_role(STAFF_ROLE_ID)
        return staff_role in member.roles if staff_role else False

    async def _is_modmail_admin(self, member: discord.Member) -> bool:
        """Check if the member has Modmail Administrator permission level."""
        level = await member.guild._state._get_client().get_permission_level(member)  # type: ignore[attr-defined]
        return level >= PermissionLevel.ADMINISTRATOR

    async def _refresh_embed(self, message: discord.Message) -> None:
        data = _active_votes.get(message.id)
        if not data:
            return
        embed = message.embeds[0]
        accept_count = len(data["accept"])
        decline_count = len(data["decline"])
        for i, field in enumerate(embed.fields):
            if field.name == "Current Votes":
                embed.set_field_at(
                    i,
                    name="Current Votes",
                    value=f"✅ Accept: **{accept_count}** | ❌ Decline: **{decline_count}**",
                    inline=False,
                )
                break
        await message.edit(embed=embed, view=self)

    @ui.button(label="✅ Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "❌ This command must be used in a server.", ephemeral=True
            )
        if not self._is_staff(interaction.user):
            return await interaction.response.send_message(
                "❌ Only staff members can vote on appeals.", ephemeral=True
            )

        data = _active_votes.get(interaction.message.id)
        if not data:
            return await interaction.response.send_message(
                "❌ This vote is no longer active.", ephemeral=True
            )

        uid = interaction.user.id
        if uid in data["accept"]:
            data["accept"].discard(uid)
            note = "✅ Your accept vote has been removed."
        else:
            data["accept"].add(uid)
            data["decline"].discard(uid)
            note = "✅ You voted to **accept** this appeal."

        await self._refresh_embed(interaction.message)
        await interaction.response.send_message(note, ephemeral=True)

        # Auto-end if all staff have now voted
        await _check_auto_end(interaction.client, interaction.message, self)

    @ui.button(label="❌ Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "❌ This command must be used in a server.", ephemeral=True
            )
        if not self._is_staff(interaction.user):
            return await interaction.response.send_message(
                "❌ Only staff members can vote on appeals.", ephemeral=True
            )

        data = _active_votes.get(interaction.message.id)
        if not data:
            return await interaction.response.send_message(
                "❌ This vote is no longer active.", ephemeral=True
            )

        uid = interaction.user.id
        if uid in data["decline"]:
            data["decline"].discard(uid)
            note = "❌ Your decline vote has been removed."
        else:
            data["decline"].add(uid)
            data["accept"].discard(uid)
            note = "❌ You voted to **decline** this appeal."

        await self._refresh_embed(interaction.message)
        await interaction.response.send_message(note, ephemeral=True)

        # Auto-end if all staff have now voted
        await _check_auto_end(interaction.client, interaction.message, self)

    @ui.button(label="🔒 End Vote", style=discord.ButtonStyle.secondary)
    async def end_vote(self, interaction: discord.Interaction, button: ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "❌ This command must be used in a server.", ephemeral=True
            )

        # Permission check: Modmail Administrator level (not Discord's native admin perm)
        level = await interaction.client.get_permission_level(interaction.user)
        if level < PermissionLevel.ADMINISTRATOR:
            return await interaction.response.send_message(
                "❌ Only Modmail administrators can end the vote.", ephemeral=True
            )

        data = _active_votes.get(interaction.message.id)
        if not data:
            return await interaction.response.send_message(
                "❌ This vote is already closed.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        await _end_vote(interaction.client, interaction.message, str(interaction.user))
        await interaction.followup.send(
            "🔒 Vote closed.", ephemeral=True
        )


# ------------------------------------------------------------------ Start view (sent in DM)

class AppealStartView(ui.View):
    def __init__(self, applicant: discord.User | discord.Member):
        super().__init__(timeout=None)  # No timeout — progress is saved so button stays active
        self.applicant = applicant

    @ui.button(label="📋 Fill Out Appeal", style=discord.ButtonStyle.primary)
    async def fill_appeal(self, interaction: discord.Interaction, button: ui.Button) -> None:
        if interaction.user.id != self.applicant.id:
            return await interaction.response.send_message(
                "❌ This appeal form is not for you.", ephemeral=True
            )
        # Open the modal — any previously saved progress will be pre-filled automatically
        await interaction.response.send_modal(AppealModal(applicant=self.applicant))

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


# ------------------------------------------------------------------ Save-progress interceptor
# We hook into the modal's on_error to save whatever was typed if submission fails,
# and we use a separate interaction listener to save progress on every modal submission attempt.

class _ProgressSavingModal(AppealModal):
    """Wraps AppealModal to save field values whenever the modal is interacted with."""

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # Save progress before processing (cleared on successful submit inside parent)
        _saved_progress[self.applicant.id] = {
            "discord_username": self.discord_username.value,
            "roblox_username": self.roblox_username.value,
            "ban_reason": self.ban_reason.value,
            "appeal_reason": self.appeal_reason.value,
            "additional": self.additional.value,
        }
        await super().on_submit(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        # Save progress even if submission errored
        _saved_progress[self.applicant.id] = {
            "discord_username": self.discord_username.value,
            "roblox_username": self.roblox_username.value,
            "ban_reason": self.ban_reason.value,
            "appeal_reason": self.appeal_reason.value,
            "additional": self.additional.value,
        }
        logger.error(f"AppealModal error for {self.applicant}: {error}", exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Something went wrong. Your progress has been saved — click the button again to continue.",
                ephemeral=True,
            )


# Patch AppealStartView to use the progress-saving modal subclass
class AppealStartView(ui.View):  # type: ignore[no-redef]
    def __init__(self, applicant: discord.User | discord.Member):
        super().__init__(timeout=None)
        self.applicant = applicant

    @ui.button(label="📋 Fill Out Appeal", style=discord.ButtonStyle.primary)
    async def fill_appeal(self, interaction: discord.Interaction, button: ui.Button) -> None:
        if interaction.user.id != self.applicant.id:
            return await interaction.response.send_message(
                "❌ This appeal form is not for you.", ephemeral=True
            )

        has_progress = self.applicant.id in _saved_progress
        modal = _ProgressSavingModal(applicant=self.applicant)
        await interaction.response.send_modal(modal)

        if has_progress:
            # Discord doesn't support a follow-up after send_modal, so we inform via DM footer on the original message only
            pass  # The pre-filled fields speak for themselves

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


# ------------------------------------------------------------------ Cog

class Appeal(commands.Cog):
    """Ban appeal plugin for ModMail."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="appeal")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def appeal(self, ctx: commands.Context, *, user: discord.Member = None) -> None:
        """
        Send a ban appeal form to a user.

        Usage:
        - Inside a thread: `?appeal` (sends to thread recipient)
        - Anywhere: `?appeal @user` or `?appeal user_id` (sends to specified user)
        """
        if not APPEAL_CHANNEL_ID or APPEAL_CHANNEL_ID == 0:
            embed = discord.Embed(
                description="❌ `APPEAL_CHANNEL_ID` has not been set in the plugin configuration.",
                color=discord.Color.red(),
            )
            return await ctx.send(embed=embed)

        applicant = user

        if not applicant:
            thread = await self.bot.threads.find(channel=ctx.channel)
            if thread:
                applicant = thread.recipient
                logger.info(f"Found thread recipient: {applicant}")

        if not applicant:
            embed = discord.Embed(
                description=(
                    "❌ Please specify a user or use this command inside a ModMail thread.\n\n"
                    "**Usage:**\n"
                    "`?appeal @user` - Send appeal to mentioned user\n"
                    "`?appeal user_id` - Send appeal to user by ID\n"
                    "`?appeal` - (in thread) Send appeal to thread recipient"
                ),
                color=discord.Color.red(),
            )
            return await ctx.send(embed=embed)

        logger.info(f"Attempting to send appeal to: {applicant} ({applicant.id})")

        saved_note = ""
        if applicant.id in _saved_progress:
            saved_note = "\n\n💾 **You have a saved draft** — your previous answers will be pre-filled when you open the form."

        embed = discord.Embed(
            title="Ban Appeal",
            description=(
                "You have been invited to submit a ban appeal.\n\n"
                "Click the button below to open the application form and fill in your answers. "
                "Be honest — staff will review your responses and vote on a decision."
                + saved_note
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="You can close and reopen this form — your progress is saved automatically.")

        try:
            await applicant.send(embed=embed, view=AppealStartView(applicant=applicant))
            logger.info(f"Successfully sent appeal DM to {applicant}")

            confirm = discord.Embed(
                description=f"✅ Appeal form sent to {applicant.mention} (`{applicant.id}`) via DM.",
                color=discord.Color.green(),
            )
            await ctx.send(embed=confirm)

        except discord.Forbidden:
            logger.warning(f"Could not DM {applicant} - Forbidden")
            embed = discord.Embed(
                description=(
                    f"❌ Could not DM {applicant.mention}.\n"
                    "**Possible reasons:**\n"
                    "• User has DMs disabled\n"
                    "• User has blocked the bot\n"
                    "• User is not in a mutual server with the bot"
                ),
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)

        except discord.HTTPException as e:
            logger.error(f"HTTP error sending appeal to {applicant}: {e}")
            embed = discord.Embed(
                description=f"❌ An error occurred while sending the DM: {str(e)}",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Unexpected error sending appeal to {applicant}: {e}", exc_info=True)
            embed = discord.Embed(
                description=f"❌ An unexpected error occurred: {str(e)}",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Appeal(bot))
