import discord
from discord.ext import commands
from discord import ui

# ============================================================
# CREDENTIALS — fill these in before running
# ============================================================
APPEAL_CHANNEL_ID = 000000000000000000   # staff appeal review channel ID
# ============================================================

# In-memory vote storage keyed by the appeal message ID
# { message_id: { "accept": set(), "decline": set(), "applicant_id": int, "roblox_username": str } }
_active_votes: dict[int, dict] = {}


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
        embed.set_footer(text="Staff: vote below. An administrator can end the vote at any time.")

        view = AppealVoteView(
            applicant_id=self.applicant.id,
            roblox_username=self.roblox_username.value,
        )
        msg = await channel.send(embed=embed, view=view)
        view.message_id = msg.id

        _active_votes[msg.id] = {
            "accept": set(),
            "decline": set(),
            "applicant_id": self.applicant.id,
            "roblox_username": self.roblox_username.value,
        }

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
        data = _active_votes.get(interaction.message.id)
        if not data:
            return await interaction.response.send_message(
                "❌ This vote is no longer active.", ephemeral=True
            )
        uid = interaction.user.id
        if uid in data["accept"]:
            data["accept"].discard(uid)
            note = "Your accept vote has been removed."
        else:
            data["accept"].add(uid)
            data["decline"].discard(uid)
            note = "You voted to **accept** this appeal."
        await self._refresh_embed(interaction.message)
        await interaction.response.send_message(note, ephemeral=True)

    @ui.button(label="❌ Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: ui.Button) -> None:
        data = _active_votes.get(interaction.message.id)
        if not data:
            return await interaction.response.send_message(
                "❌ This vote is no longer active.", ephemeral=True
            )
        uid = interaction.user.id
        if uid in data["decline"]:
            data["decline"].discard(uid)
            note = "Your decline vote has been removed."
        else:
            data["decline"].add(uid)
            data["accept"].discard(uid)
            note = "You voted to **decline** this appeal."
        await self._refresh_embed(interaction.message)
        await interaction.response.send_message(note, ephemeral=True)

    @ui.button(label="🔒 End Vote", style=discord.ButtonStyle.secondary)
    async def end_vote(self, interaction: discord.Interaction, button: ui.Button) -> None:
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "❌ Only administrators can end the vote.", ephemeral=True
            )

        data = _active_votes.pop(interaction.message.id, None)
        if not data:
            return await interaction.response.send_message(
                "❌ This vote is already closed.", ephemeral=True
            )

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

        embed = interaction.message.embeds[0]
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
        embed.set_footer(text=f"Vote ended by {interaction.user} • {interaction.user.id}")

        for child in self.children:
            child.disabled = True

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(
            f"Vote closed. Result: **{result_label}**", ephemeral=True
        )

        applicant = interaction.client.get_user(data["applicant_id"])
        if applicant:
            try:
                await applicant.send(dm_msg)
            except discord.Forbidden:
                pass


# ------------------------------------------------------------------ Start view (sent in DM)

class AppealStartView(ui.View):
    def __init__(self, applicant: discord.User | discord.Member):
        super().__init__(timeout=600)
        self.applicant = applicant

    @ui.button(label="📋 Fill Out Appeal", style=discord.ButtonStyle.primary)
    async def fill_appeal(self, interaction: discord.Interaction, button: ui.Button) -> None:
        if interaction.user.id != self.applicant.id:
            return await interaction.response.send_message(
                "❌ This appeal form is not for you.", ephemeral=True
            )
        await interaction.response.send_modal(AppealModal(applicant=self.applicant))
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


# ------------------------------------------------------------------ Cog

class Appeal(commands.Cog):
    """Ban appeal plugin for ModMail."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="appeal")
    async def appeal(self, ctx: commands.Context) -> None:
        """Send a ban appeal form to the thread recipient. Must be used inside a ModMail thread."""
        thread = self.bot.threads.find_by_channel_id(ctx.channel.id)
        if not thread:
            embed = discord.Embed(
                description="❌ This command can only be used inside a ModMail thread.",
                color=discord.Color.red(),
            )
            return await ctx.send(embed=embed)

        if not APPEAL_CHANNEL_ID:
            embed = discord.Embed(
                description="❌ `APPEAL_CHANNEL_ID` has not been set in `appeal.py`.",
                color=discord.Color.red(),
            )
            return await ctx.send(embed=embed)

        applicant = thread.recipient
        if applicant is None:
            embed = discord.Embed(
                description="❌ Could not find the thread recipient.",
                color=discord.Color.red(),
            )
            return await ctx.send(embed=embed)

        embed = discord.Embed(
            title="Ban Appeal",
            description=(
                "You have been invited to submit a ban appeal.\n\n"
                "Click the button below to open the application form and fill in your answers. "
                "Be honest — staff will review your responses and vote on a decision."
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="This form expires in 10 minutes.")

        try:
            await applicant.send(embed=embed, view=AppealStartView(applicant=applicant))
        except discord.Forbidden:
            embed = discord.Embed(
                description=f"❌ Could not DM {applicant.mention}. They may have DMs disabled.",
                color=discord.Color.red(),
            )
            return await ctx.send(embed=embed)

        confirm = discord.Embed(
            description=f"✅ Appeal form sent to {applicant.mention} via DM.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=confirm)

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
        raise error


async def setup(bot):
    await bot.add_cog(Appeal(bot))
