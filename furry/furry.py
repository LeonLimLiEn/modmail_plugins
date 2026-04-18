from __future__ import annotations

import discord
from discord.ext import commands
import aiohttp
from PIL import Image, ImageOps
from io import BytesIO
import os

from core import checks
from core.models import PermissionLevel


class Furrify(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="furrify")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def furrify(self, ctx, member: discord.Member = None):
        try:
            target = member or ctx.author

            await ctx.send("🐾 Furrifying...")

            # -------------------------
            # GET AVATAR (FIXED + RELIABLE)
            # -------------------------
            avatar_url = str(
                target.display_avatar.with_format("png").with_size(512)
            )

            async with aiohttp.ClientSession() as session:
                async with session.get(avatar_url) as resp:
                    if resp.status != 200:
                        return await ctx.send("❌ Failed to download avatar.")
                    avatar_bytes = await resp.read()

            avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA")

            # -------------------------
            # CENTER CROP (FIXED)
            # -------------------------
            avatar = ImageOps.fit(avatar, (512, 512), method=Image.LANCZOS)

            # -------------------------
            # LOAD OVERLAY SAFELY
            # -------------------------
            base_dir = os.path.dirname(os.path.abspath(__file__))
            overlay_path = os.path.join(base_dir, "furry_ears.png")

            if not os.path.exists(overlay_path):
                return await ctx.send("❌ Missing furry_ears.png in plugin folder.")

            overlay = Image.open(overlay_path).convert("RGBA")
            overlay = overlay.resize((512, 512))

            # -------------------------
            # COMBINE
            # -------------------------
            combined = Image.alpha_composite(avatar, overlay)

            # -------------------------
            # OUTPUT
            # -------------------------
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
