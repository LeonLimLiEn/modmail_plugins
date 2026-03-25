"""
Modmail Plugin: Roblox Ban
===========================
Adds a command that lets moderators ban a Roblox user directly by username.

Usage (in Discord):
  .rban <roblox_username> <reason>
  Example: .rban xxleoncakewoofxx Exploiting in game

SETUP:
  1. Drop this file into your Modmail bot's `plugins/` directory.
  2. Fill in the two configuration values below.
  3. Restart your bot.

Permissions: only users with Moderator level or above in Modmail can use .rban.
"""

import aiohttp
import discord
from discord.ext import commands
from core import checks
from core.models import PermissionLevel

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

API_SERVER_URL = "https://roblox-ban-server-cpca.onrender.com"
SHARED_SECRET  = "PASTE_YOUR_SHARED_SECRET_HERE"  # must match the value in server.py

# ──────────────────────────────────────────────────────────────────────────────


class RobloxBan(commands.Cog):
    """Lets moderators ban Roblox users directly by username."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_roblox_id(self, username: str) -> tuple:
        """Look up a Roblox user ID by username. Returns (id, exact_name) or (None, None)."""
        url = "https://users.roblox.com/v1/usernames/users"
        payload = {"usernames": [username], "excludeBannedUsers": False}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    users = data.get("data", [])
                    if users:
                        return int(users[0]["id"]), users[0]["name"]
                return None, None

    async def queue_ban(self, roblox_user_id: int, roblox_username: str) -> bool:
        """Post the ban to the API server queue. Returns True on success."""
        url = f"{API_SERVER_URL.rstrip('/')}/bans"
        payload = {
            "robloxUserId": roblox_user_id,
            "robloxUsername": roblox_username,
            "secret": SHARED_SECRET,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                return resp.status == 201

    @commands.command(name="rban")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def rban(self, ctx: commands.Context, *, args: str = ""):
        """Ban a Roblox user by their username. Usage: .rban <username> <reason>"""

        await ctx.message.delete()

        # Parse username (first word) and reason (everything after)
        parts = args.strip().split(" ", 1)
        roblox_username = parts[0] if len(parts) >= 1 else ""
        reason = parts[1] if len(parts) >= 2 else ""

        # Validate both fields are provided
        if not roblox_username and not reason:
            embed = discord.Embed(
                title="⚠️ Missing Information",
                description="Please provide a Roblox username and a reason.",
                color=discord.Color.orange()
            )
            embed.add_field(name="Usage", value="`.rban <roblox_username> <reason>`", inline=False)
            embed.add_field(name="Example", value="`.rban xxleoncakewoofxx Exploiting in game`", inline=False)
            await ctx.send(embed=embed)
            return

        if not roblox_username:
            embed = discord.Embed(
                title="⚠️ Missing Roblox Username",
                description="Please include the Roblox username you want to ban.",
                color=discord.Color.orange()
            )
            embed.add_field(name="Usage", value="`.rban <roblox_username> <reason>`", inline=False)
            await ctx.send(embed=embed)
            return

        if not reason:
            embed = discord.Embed(
                title="⚠️ Missing Reason",
                description=f"Please provide a reason for banning **{roblox_username}**.",
                color=discord.Color.orange()
            )
            embed.add_field(name="Usage", value="`.rban <roblox_username> <reason>`", inline=False)
            await ctx.send(embed=embed)
            return

        # Look up the Roblox account
        status_msg = await ctx.send(f"🔍 Looking up Roblox user **{roblox_username}**...")
        roblox_id, exact_name = await self.get_roblox_id(roblox_username)

        if roblox_id is None:
            embed = discord.Embed(
                title="❌ User Not Found",
                description=f"No Roblox account found for **{roblox_username}**.\nDouble-check the username and try again.",
                color=discord.Color.red()
            )
            await status_msg.edit(content=None, embed=embed)
            return

        # Queue the ban
        success = await self.queue_ban(roblox_id, exact_name)

        if success:
            embed = discord.Embed(
                title="🔨 Player Banned",
                color=discord.Color.red()
            )
            embed.add_field(name="Roblox Username", value=exact_name, inline=True)
            embed.add_field(name="Reason", value=reason, inline=True)
            embed.add_field(
                name="Status",
                value="Ban queued — will be applied next time a game server is running.",
                inline=False
            )
            embed.set_footer(text=f"Banned by {ctx.author.display_name}")
            await status_msg.edit(content=None, embed=embed)
        else:
            embed = discord.Embed(
                title="❌ Failed to Queue Ban",
                description=f"Found **{exact_name}** but couldn't reach the ban server.\nCheck that your server is running and the shared secret matches.",
                color=discord.Color.red()
            )
            await status_msg.edit(content=None, embed=embed)

    @rban.error
    async def rban_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CheckFailure):
            await ctx.send("❌ You don't have permission to use this command.")


async def setup(bot: commands.Bot):
    await bot.add_cog(RobloxBan(bot))
