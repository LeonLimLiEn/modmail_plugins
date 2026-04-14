from __future__ import annotations

import discord
from discord.ext import commands
import asyncio
from datetime import datetime
from typing import List, Optional

# =========================
# ADVANCED ANNOUNCEMENT SYSTEM
# =========================

class AnnouncementSession:
    def __init__(self, ctx: commands.Context):
        self.ctx = ctx
        self.title: Optional[str] = None
        self.description: Optional[str] = None
        self.color: int = 0x2F3136
        self.image: Optional[str] = None
        self.thumbnail: Optional[str] = None
        self.footer: Optional[str] = None
        self.buttons: List[dict] = []
        self.channels: List[discord.TextChannel] = []
        self.schedule_time: Optional[datetime] = None
        self.anonymous: bool = True

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=self.title,
            description=self.description,
            color=self.color
        )

        if self.image:
            embed.set_image(url=self.image)

        if self.thumbnail:
            embed.set_thumbnail(url=self.thumbnail)

        if self.footer:
            embed.set_footer(text=self.footer)

        return embed


class ButtonView(discord.ui.View):
    def __init__(self, buttons: List[dict]):
        super().__init__(timeout=None)

        for btn in buttons:
            self.add_item(discord.ui.Button(label=btn["label"], url=btn["url"]))


class ConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.value = None

    @discord.ui.button(label="Send", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()


class Announcement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def announce(self, ctx: commands.Context):
        """Start advanced announcement builder"""

        session = AnnouncementSession(ctx)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        await ctx.send("**Enter title:**")
        msg = await self.bot.wait_for("message", check=check)
        session.title = msg.content

        await ctx.send("**Enter description:**")
        msg = await self.bot.wait_for("message", check=check)
        session.description = msg.content

        await ctx.send("**Enter hex color (or 'skip'):**")
        msg = await self.bot.wait_for("message", check=check)
        if msg.content.lower() != "skip":
            session.color = int(msg.content.replace("#", ""), 16)

        await ctx.send("**Enter image URL (or 'skip'):**")
        msg = await self.bot.wait_for("message", check=check)
        if msg.content.lower() != "skip":
            session.image = msg.content

        await ctx.send("**Enter thumbnail URL (or 'skip'):**")
        msg = await self.bot.wait_for("message", check=check)
        if msg.content.lower() != "skip":
            session.thumbnail = msg.content

        await ctx.send("**Enter footer (or 'skip'):**")
        msg = await self.bot.wait_for("message", check=check)
        if msg.content.lower() != "skip":
            session.footer = msg.content

        await ctx.send("**Mention channels to send (separate by space):**")
        msg = await self.bot.wait_for("message", check=check)
        session.channels = msg.channel_mentions

        await ctx.send("**Add button? (yes/no)**")
        msg = await self.bot.wait_for("message", check=check)

        if msg.content.lower() == "yes":
            await ctx.send("Button label:")
            label = (await self.bot.wait_for("message", check=check)).content

            await ctx.send("Button URL:")
            url = (await self.bot.wait_for("message", check=check)).content

            session.buttons.append({"label": label, "url": url})

        await ctx.send("**Schedule? (YYYY-MM-DD HH:MM or 'no'):**")
        msg = await self.bot.wait_for("message", check=check)

        if msg.content.lower() != "no":
            session.schedule_time = datetime.strptime(msg.content, "%Y-%m-%d %H:%M")

        embed = session.build_embed()
        view = ButtonView(session.buttons) if session.buttons else None

        preview = await ctx.send("**Preview:**", embed=embed, view=view)

        confirm_view = ConfirmView()
        await ctx.send("Send announcement?", view=confirm_view)

        await confirm_view.wait()

        if not confirm_view.value:
            return await ctx.send("Cancelled.")

        async def send():
            for channel in session.channels:
                try:
                    msg = await channel.send(embed=embed, view=view)

                    if channel.type == discord.ChannelType.news:
                        await msg.publish()

                except Exception:
                    pass

        if session.schedule_time:
            delay = (session.schedule_time - datetime.utcnow()).total_seconds()
            if delay > 0:
                await ctx.send(f"Scheduled in {int(delay)} seconds.")
                await asyncio.sleep(delay)

        await send()
        await ctx.send("Announcement sent.")


async def setup(bot):
    await bot.add_cog(Announcement(bot))
