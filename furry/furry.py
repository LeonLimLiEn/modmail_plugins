from __future__ import annotations

import discord
from discord.ext import commands
import aiohttp
from PIL import Image
from io import BytesIO
import os

from core import checks
from core.models import PermissionLevel


class Furrify(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="furrify")
    async def furrify(self, ctx, member: discord.Member = None):
        try:
            # -----------------------------
            # MANUAL PERMISSION CHECK (IMPORTANT)
            # -----------------------------
            if not await self.bot.config.get_user_permission_level(ctx.author) >= PermissionLevel.ADMINISTRATOR:
                return await ctx.send("❌ You don’t have permission to use this command (Administrator required).")

            target = member or ctx.author

            await ctx.send("🐾 Furrifying...")

            # -----------------------------
            # GET AVATAR
            # -----------------------------
            avatar_url = target.display_avatar.replace(format="png", size=512).url

            async with aiohttp.ClientSession() as session:
                async with session.get(avatar_url) as resp:
                    if resp.status != 200:
                        return await ctx.send("❌ Could not download the user's avatar.")
                    avatar_bytes = await resp.read()

            avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA")

            # -----------------------------
            # CHECK OVERLAY FILE
            # -----------------------------
            base_dir = os.path.dirname(os.path.abspath(__file__))
            overlay_path = os.path.join(base_dir, "furry_ears.png")

            if not os.path.exists(overlay_path):
                return await ctx.send(
                    "❌ Missing required file: `furry_ears.png`\n"
                    "Please upload it to the plugin folder."
                )

            overlay = Image.open(overlay_path).convert("RGBA")
            overlay = overlay.resize(avatar.size)

            # -----------------------------
            # COMBINE IMAGES
            # -----------------------------
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

        except Exception as e:
            await ctx.send(f"❌ Unexpected error:\n```{e}```")
            raise


async def setup(bot):
    await bot.add_cog(Furrify(bot))
