from __future__ import annotations

import discord
from discord.ext import commands
from typing import Optional, List

from core import checks
from core.models import PermissionLevel

# =========================
# MODMAIL ADVANCED EMBED SYSTEM (PROFESSIONAL + ROLE PING)
# =========================

class AnnouncementModal(discord.ui.Modal, title="Create Professional Announcement"):
    title_input = discord.ui.TextInput(label="Title", required=True, max_length=256)
    desc_input = discord.ui.TextInput(label="Description", style=discord.TextStyle.long, required=True)
    color_input = discord.ui.TextInput(label="Hex Color (optional)", required=False, placeholder="#5865F2")
    image_input = discord.ui.TextInput(label="Image URL (optional)", required=False)

    def __init__(self, cog, ctx):
        super().__init__()
        self.cog = cog
        self.ctx = ctx

    async def on_submit(self, interaction: discord.Interaction):
        color = 0x5865F2

        if self.color_input.value:
            try:
                color = int(self.color_input.value.replace("#", ""), 16)
            except:
                pass

        embed = discord.Embed(
            title=self.title_input.value,
            description=self.desc_input.value,
            color=color
        )

        if self.image_input.value:
            embed.set_image(url=self.image_input.value)

        view = ConfirmView(self.cog, embed, self.ctx)

        await interaction.response.send_message(
            "Here is a preview of your announcement. Please review it carefully before proceeding.",
            embed=embed,
            view=view,
            ephemeral=True
        )


class ConfirmView(discord.ui.View):
    def __init__(self, cog, embed, ctx):
        super().__init__(timeout=120)
        self.cog = cog
        self.embed = embed
        self.ctx = ctx

    @discord.ui.button(label="Send Announcement", style=discord.ButtonStyle.green)
    async def send(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Please mention the channel(s) where this announcement should be sent.",
            ephemeral=True
        )

        def check(m):
            return m.author == self.ctx.author and m.channel == self.ctx.channel

        try:
            msg = await self.cog.bot.wait_for("message", timeout=60, check=check)
            channels = msg.channel_mentions or [self.ctx.channel]
        except:
            return await interaction.followup.send("Operation timed out. Please try again.", ephemeral=True)

        await interaction.followup.send(
            "Optionally, mention a role to notify (or type 'skip').",
            ephemeral=True
        )

        try:
            role_msg = await self.cog.bot.wait_for("message", timeout=60, check=check)
            roles = role_msg.role_mentions
            role_ping = " ".join(role.mention for role in roles) if roles else None
        except:
            role_ping = None

        for ch in channels:
            try:
                content = role_ping if role_ping else None
                sent = await ch.send(content=content, embed=self.embed)

                if ch.type == discord.ChannelType.news:
                    await sent.publish()
            except:
                continue

        await interaction.followup.send("Your announcement has been successfully delivered.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("The announcement process has been cancelled.", ephemeral=True)
        self.stop()


class Announcement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="embed")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def embed_command(self, ctx: commands.Context):
        """Launch the professional embed announcement system"""

        view = discord.ui.View()

        async def open_modal(interaction: discord.Interaction):
            await interaction.response.send_modal(AnnouncementModal(self, ctx))

        button = discord.ui.Button(label="Create Announcement", style=discord.ButtonStyle.primary)
        button.callback = open_modal
        view.add_item(button)

        await ctx.send(
            "Click the button below to begin creating a professional announcement.",
            view=view
        )


async def setup(bot):
    await bot.add_cog(Announcement(bot))
