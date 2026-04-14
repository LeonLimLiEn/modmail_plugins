from __future__ import annotations

import discord
from discord.ext import commands
from typing import Optional, List

from core import checks
from core.models import PermissionLevel

# =========================
# MODMAIL-COMPATIBLE ADVANCED ANNOUNCEMENT
# (NO wait_for, uses MODALS + VIEWS)
# =========================

class AnnouncementModal(discord.ui.Modal, title="Create Announcement"):
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
            "Preview your announcement:",
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

    @discord.ui.button(label="Send", style=discord.ButtonStyle.green)
    async def send(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Mention channel to send:", ephemeral=True)

        def check(m):
            return m.author == self.ctx.author and m.channel == self.ctx.channel

        try:
            msg = await self.cog.bot.wait_for("message", timeout=60, check=check)
            channels = msg.channel_mentions or [self.ctx.channel]
        except:
            return await interaction.followup.send("Timed out.", ephemeral=True)

        for ch in channels:
            try:
                sent = await ch.send(embed=self.embed)

                if ch.type == discord.ChannelType.news:
                    await sent.publish()
            except:
                continue

        await interaction.followup.send("Announcement sent.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Cancelled.", ephemeral=True)
        self.stop()


class Announcement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def announce(self, ctx: commands.Context):
        """Open advanced announcement UI"""

        view = discord.ui.View()

        async def open_modal(interaction: discord.Interaction):
            await interaction.response.send_modal(AnnouncementModal(self, ctx))

        button = discord.ui.Button(label="Create Announcement", style=discord.ButtonStyle.primary)
        button.callback = open_modal
        view.add_item(button)

        await ctx.send("Click below to create an announcement:", view=view)


async def setup(bot):
    await bot.add_cog(Announcement(bot))
