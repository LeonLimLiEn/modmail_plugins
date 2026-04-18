from __future__ import annotations

import discord
from discord.ext import commands
import aiohttp
from PIL import Image
from io import BytesIO

from core import checks
from core.models import PermissionLevel


class Furrify(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="furrify")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)  # ✅ Modmail admin
    async def furrify(self, ctx, member: discord.Member = None):
        target = member or ctx.author

        avatar_url = target.display_avatar.replace(format="png", size=512).url

        # Download avatar
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url) as resp:
                avatar_bytes = await resp.read()

        avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA")

        # Overlay
        overlay = Image.open("furry_ears.png").convert("RGBA")
        overlay = overlay.resize(avatar.size)

        combined = Image.alpha_composite(avatar, overlay)

        buffer = BytesIO()
        combined.save(buffer, format="PNG")
        buffer.seek(0)

        file = discord.File(buffer, filename="furrified.png")

        embed = discord.Embed(
            title="🐾 Furrification Complete",
            description=f"{target.mention} has been successfully furrified.",
            color=discord.Color.purple()
        )

        embed.set_image(url="attachment://furrified.png")

        await ctx.send(file=file, embed=embed)


async def setup(bot):
    await bot.add_cog(Furrify(bot))
