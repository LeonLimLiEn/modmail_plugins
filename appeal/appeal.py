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

# Saved drafts keyed by user ID — persists across modal dismissals
# { user_id: { "discord_username": str, "roblox_username": str, "ban_reason": str,
#              "appeal_reason": str, "additional": str } }
_drafts: dict[int, dict] = {}


# ------------------------------------------------------------------ Shared helpers

async def _is_modmail_admin(bot: commands.Bot, interaction: discord.Interaction) -> tuple[bool, str]:
    """
    Return (True, "") if the user has Modmail ADMINISTRATOR level or higher.
    Return (False, reason) otherwise so the caller can show a useful message.
    """
    if interaction.guild is None:
        return False, "This must be used inside a server."

    member = interaction.guild.get_member(interaction.user.id)
    if member is None:
        return False, f"Could not resolve your member object (id: {interaction.user.id})."

    try:
        level = await bot.get_permission_level(member)
    except Exception as e:
        logger.error(f"get_permission_level raised for {member}: {e}", exc_info=True)
        return False, f"Permission check error: `{type(e).__name__}: {e}`"

    if level >= PermissionLevel.ADMINISTRATOR:
        return True, ""

    return False, f"Your Modmail level is `{level}` — need `{PermissionLevel.ADMINISTRATOR}` or higher."


def _build_prefilled_inputs(user_id: int) -> dict:
    """Return saved draft field values for a user, or empty strings."""
    d = _drafts.get(user_id, {})
    return {
        "discord_username": d.get("discord_username", ""),
        "roblox_username":  d.get("roblox_username", ""),
        "ban_reason":        d.get("ban_reason", ""),
        "appeal_reason":     d.get("appeal_reason", ""),
        "additional":        d.get("additional", ""),
    }


async def _end_vote(
    bot: commands.Bot,
    message: discord.Message,
    ended_by: str,
    view: "AppealVoteView | None" = None,
) -> None:
    """Close a vote, update the embed, and DM the applicant the result."""
    data = _active_votes.pop(message.id, None)
    if not data:
        return

    accept_count  = len(data["accept"])
    decline_count = len(data["decline"])

    if accept_count > decline_count:
        result_label = "✅ ACCEPTED"
        color  = discord.Color.green()
        dm_msg = (
            f"✅ Your ban appeal for Roblox user **{data['roblox_username']}** has been **accepted**.\n"
            "Please contact staff for next steps."
        )
    elif decline_count > accept_count:
        result_label = "❌ DECLINED"
        color  = discord.Color.red()
        dm_msg = f"❌ Your ban appeal for Roblox user **{data['roblox_username']}** has been **declined**."
    else:
        result_label = "⚖️ TIE — No decision"
        color  = discord.Color.greyple()
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

    # Disable whichever view we have; fall back to a plain empty view if none was passed
    if view is not None:
        for child in view.children:
            child.disabled = True
        await message.edit(embed=embed, view=view)
    else:
        await message.edit(embed=embed, view=ui.View())

    applicant = bot.get_user(data["applicant_id"])
    if applicant:
        try:
            await applicant.send(dm_msg)
        except discord.Forbidden:
            logger.warning(f"Could not DM user {applicant.id} with appeal result")


async def _check_auto_end(bot: commands.Bot, message: discord.Message, view: "AppealVoteView") -> bool:
    """
    Check whether every non-bot staff member has cast a vote.
    If so, auto-end the vote and return True.
    """
    data = _active_votes.get(message.id)
    if not data:
        return False

    guild = message.channel.guild
    staff_role = guild.get_role(STAFF_ROLE_ID)
    if not staff_role:
        return False

    staff_ids = {m.id for m in staff_role.members if not m.bot}
    if not staff_ids:
        return False

    voted_ids = data["accept"] | data["decline"]
    if staff_ids <= voted_ids:
        await _end_vote(bot, message, "automatic (all staff voted)", view=view)
        await message.channel.send(
            f"🔒 Vote auto-closed — all {len(staff_ids)} staff members have cast their vote."
        )
        return True

    return False


# ------------------------------------------------------------------ Modals

class _AppealFormBase(ui.Modal, title="Ban Appeal Application"):
    """Shared field definitions used by both the draft and submit modals."""

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

    def __init__(self, applicant: discord.User | discord.Member) -> None:
        super().__init__()
        self.applicant = applicant
        # Pre-fill all fields from any existing draft
        saved = _build_prefilled_inputs(applicant.id)
        if saved["discord_username"]:
            self.discord_username.default = saved["discord_username"]
        if saved["roblox_username"]:
            self.roblox_username.default = saved["roblox_username"]
        if saved["ban_reason"]:
            self.ban_reason.default = saved["ban_reason"]
        if saved["appeal_reason"]:
            self.appeal_reason.default = saved["appeal_reason"]
        if saved["additional"]:
            self.additional.default = saved["additional"]

    def _snapshot(self) -> dict:
        return {
            "discord_username": self.discord_username.value,
            "roblox_username":  self.roblox_username.value,
            "ban_reason":        self.ban_reason.value,
            "appeal_reason":     self.appeal_reason.value,
            "additional":        self.additional.value,
        }


class SaveDraftModal(_AppealFormBase, title="Save Draft — Ban Appeal"):
    """
    Opens the same form as the appeal, but on submit saves answers as a draft
    instead of posting the appeal. The user can fill this in and click Submit
    to safely store their progress, then use '📋 Submit Appeal' when ready.
    """

    async def on_submit(self, interaction: discord.Interaction) -> None:
        _drafts[self.applicant.id] = self._snapshot()
        await interaction.response.send_message(
            "💾 Draft saved! Your answers are stored — click **📋 Submit Appeal** whenever you're ready to send it.",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.error(f"SaveDraftModal error for {self.applicant}: {error}", exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Something went wrong saving your draft. Please try again.",
                ephemeral=True,
            )


class AppealModal(_AppealFormBase, title="Ban Appeal Application"):
    """Submits the appeal to the staff channel."""

    def __init__(self, applicant: discord.User | discord.Member, dm_message: discord.Message | None = None) -> None:
        super().__init__(applicant)
        self.dm_message = dm_message  # The DM message holding the start view, so we can disable it after submit

    async def on_submit(self, interaction: discord.Interaction) -> None:
        channel = interaction.client.get_channel(APPEAL_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message(
                "❌ The appeal review channel could not be found. Please contact an administrator.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="📋 New Ban Appeal", color=discord.Color.blurple())
        embed.add_field(
            name="Applicant",
            value=f"{self.applicant.mention} (`{self.applicant.id}`)",
            inline=False,
        )
        embed.add_field(name="Discord Username", value=self.discord_username.value, inline=True)
        embed.add_field(name="Roblox Username",  value=self.roblox_username.value,  inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="What they were banned for",    value=self.ban_reason.value,    inline=False)
        embed.add_field(name="Why they should be unbanned",  value=self.appeal_reason.value, inline=False)
        if self.additional.value.strip():
            embed.add_field(name="Additional Info", value=self.additional.value, inline=False)
        embed.add_field(name="Current Votes", value="✅ Accept: **0** | ❌ Decline: **0**", inline=False)
        embed.set_thumbnail(url=self.applicant.display_avatar.url)
        embed.set_footer(text="Staff: vote below. A Modmail administrator can end the vote at any time.")

        view = AppealVoteView(
            bot=interaction.client,
            applicant_id=self.applicant.id,
            roblox_username=self.roblox_username.value,
        )

        staff_ping = f"<@&{STAFF_ROLE_ID}>" if STAFF_ROLE_ID else None
        msg = await channel.send(content=staff_ping, embed=embed, view=view)
        view.message_id = msg.id

        _active_votes[msg.id] = {
            "accept":           set(),
            "decline":          set(),
            "applicant_id":     self.applicant.id,
            "roblox_username":  self.roblox_username.value,
        }

        # Clear draft now that appeal is submitted
        _drafts.pop(self.applicant.id, None)

        # Disable the DM start view so they can't submit again
        if self.dm_message:
            disabled_view = ui.View()
            disabled_view.add_item(ui.Button(label="💾 Save Draft", style=discord.ButtonStyle.secondary, disabled=True))
            disabled_view.add_item(ui.Button(label="📋 Appeal Submitted", style=discord.ButtonStyle.primary, disabled=True))
            try:
                await self.dm_message.edit(view=disabled_view)
            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            "✅ Your appeal has been submitted and is under review by staff. You will be notified of the outcome.",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.error(f"AppealModal error for {self.applicant}: {error}", exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Something went wrong submitting your appeal. Your draft is still saved — please try again.",
                ephemeral=True,
            )


# ------------------------------------------------------------------ Vote view

class AppealVoteView(ui.View):
    def __init__(self, bot: commands.Bot, applicant_id: int, roblox_username: str):
        super().__init__(timeout=None)
        self.bot             = bot
        self.applicant_id    = applicant_id
        self.roblox_username = roblox_username
        self.message_id: int | None = None

    def _is_staff(self, member: discord.Member) -> bool:
        if not STAFF_ROLE_ID:
            return False
        staff_role = member.guild.get_role(STAFF_ROLE_ID)
        return staff_role in member.roles if staff_role else False

    async def _refresh_embed(self, message: discord.Message) -> None:
        data = _active_votes.get(message.id)
        if not data:
            return
        embed = message.embeds[0]
        accept_count  = len(data["accept"])
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
            return await interaction.response.send_message("❌ This command must be used in a server.", ephemeral=True)
        if not self._is_staff(interaction.user):
            return await interaction.response.send_message("❌ Only staff members can vote on appeals.", ephemeral=True)

        data = _active_votes.get(interaction.message.id)
        if not data:
            return await interaction.response.send_message("❌ This vote is no longer active.", ephemeral=True)

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
        await _check_auto_end(self.bot, interaction.message, self)

    @ui.button(label="❌ Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ This command must be used in a server.", ephemeral=True)
        if not self._is_staff(interaction.user):
            return await interaction.response.send_message("❌ Only staff members can vote on appeals.", ephemeral=True)

        data = _active_votes.get(interaction.message.id)
        if not data:
            return await interaction.response.send_message("❌ This vote is no longer active.", ephemeral=True)

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
        await _check_auto_end(self.bot, interaction.message, self)

    @ui.button(label="🔒 End Vote", style=discord.ButtonStyle.secondary)
    async def end_vote(self, interaction: discord.Interaction, button: ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ This command must be used in a server.", ephemeral=True)

        # Modmail permission check — not Discord's native admin perm
        allowed, reason = await _is_modmail_admin(self.bot, interaction)
        if not allowed:
            return await interaction.response.send_message(f"❌ {reason}", ephemeral=True)

        if not _active_votes.get(interaction.message.id):
            return await interaction.response.send_message("❌ This vote is already closed.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        try:
            # Pass self so _end_vote disables the actual live buttons
            await _end_vote(interaction.client, interaction.message, str(interaction.user), view=self)
        except Exception as e:
            logger.error(f"_end_vote failed: {e}", exc_info=True)
            return await interaction.followup.send("❌ Something went wrong closing the vote. Check bot logs.", ephemeral=True)
        await interaction.followup.send("🔒 Vote closed.", ephemeral=True)


# ------------------------------------------------------------------ DM start view

class AppealStartView(ui.View):
    """
    Sent to the applicant via DM. Two buttons:
      • 💾 Save Draft  — fills out the form and saves without submitting
      • 📋 Submit Appeal — fills out the form (pre-filled from draft) and submits
    """

    def __init__(self, applicant: discord.User | discord.Member):
        super().__init__(timeout=None)  # No timeout; user can come back any time
        self.applicant = applicant

    def _check_owner(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.applicant.id

    @ui.button(label="💾 Save Draft", style=discord.ButtonStyle.secondary, row=0)
    async def save_draft(self, interaction: discord.Interaction, button: ui.Button) -> None:
        if not self._check_owner(interaction):
            return await interaction.response.send_message("❌ This appeal form is not for you.", ephemeral=True)
        await interaction.response.send_modal(SaveDraftModal(applicant=self.applicant))

    @ui.button(label="📋 Submit Appeal", style=discord.ButtonStyle.primary, row=0)
    async def submit_appeal(self, interaction: discord.Interaction, button: ui.Button) -> None:
        if not self._check_owner(interaction):
            return await interaction.response.send_message("❌ This appeal form is not for you.", ephemeral=True)
        await interaction.response.send_modal(AppealModal(applicant=self.applicant, dm_message=interaction.message))


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
        if not APPEAL_CHANNEL_ID:
            return await ctx.send(embed=discord.Embed(
                description="❌ `APPEAL_CHANNEL_ID` has not been set in the plugin configuration.",
                color=discord.Color.red(),
            ))

        applicant = user
        if not applicant:
            thread = await self.bot.threads.find(channel=ctx.channel)
            if thread:
                applicant = thread.recipient
                logger.info(f"Found thread recipient: {applicant}")

        if not applicant:
            return await ctx.send(embed=discord.Embed(
                description=(
                    "❌ Please specify a user or use this command inside a ModMail thread.\n\n"
                    "**Usage:**\n"
                    "`?appeal @user` — Send appeal to mentioned user\n"
                    "`?appeal user_id` — Send appeal to user by ID\n"
                    "`?appeal` — (in thread) Send appeal to thread recipient"
                ),
                color=discord.Color.red(),
            ))

        logger.info(f"Attempting to send appeal to: {applicant} ({applicant.id})")

        has_draft = applicant.id in _drafts
        draft_note = (
            "\n\n💾 **You have a saved draft.** Click **💾 Save Draft** to update it, "
            "or **📋 Submit Appeal** to send your appeal with the draft pre-filled."
            if has_draft else
            "\n\nUse **💾 Save Draft** to save your progress at any time, "
            "then click **📋 Submit Appeal** when you're ready to send."
        )

        embed = discord.Embed(
            title="Ban Appeal",
            description=(
                "You have been invited to submit a ban appeal.\n\n"
                "Fill in your answers honestly — staff will review your responses and vote on a decision."
                + draft_note
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Your draft is saved between sessions. Take your time.")

        try:
            await applicant.send(embed=embed, view=AppealStartView(applicant=applicant))
            logger.info(f"Successfully sent appeal DM to {applicant}")
            await ctx.send(embed=discord.Embed(
                description=f"✅ Appeal form sent to {applicant.mention} (`{applicant.id}`) via DM.",
                color=discord.Color.green(),
            ))

        except discord.Forbidden:
            logger.warning(f"Could not DM {applicant} - Forbidden")
            await ctx.send(embed=discord.Embed(
                description=(
                    f"❌ Could not DM {applicant.mention}.\n"
                    "**Possible reasons:**\n"
                    "• User has DMs disabled\n"
                    "• User has blocked the bot\n"
                    "• User is not in a mutual server with the bot"
                ),
                color=discord.Color.red(),
            ))

        except discord.HTTPException as e:
            logger.error(f"HTTP error sending appeal to {applicant}: {e}")
            await ctx.send(embed=discord.Embed(
                description=f"❌ An error occurred while sending the DM: {str(e)}",
                color=discord.Color.red(),
            ))

        except Exception as e:
            logger.error(f"Unexpected error sending appeal to {applicant}: {e}", exc_info=True)
            await ctx.send(embed=discord.Embed(
                description=f"❌ An unexpected error occurred: {str(e)}",
                color=discord.Color.red(),
            ))


async def setup(bot):
    await bot.add_cog(Appeal(bot))
