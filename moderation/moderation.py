"""
Modmail Plugin: Roblox Ban
===========================
Adds a command that lets moderators ban a Roblox user directly by username.

Usage (in Discord):
  .rban <roblox_username>
  Example: .rban xxleoncakewoofxx

SETUP:
  1. Drop this file into your Modmail bot's `plugins/` directory.
  2. Fill in the two configuration values below.
  3. Paste your server URL (the URL of your API server running this ban queue).
  4. Restart your bot.

Permissions: only users with Moderator level or above in Modmail can use .rban.
"""

import aiohttp
import discord
from discord.ext import commands
from core import checks
from core.models import PermissionLevel

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

API_SERVER_URL = "https://roblox-ban-server-cpca.onrender.com"
SHARED_SECRET  = "EMAdabest"  # must match the value in the API server

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
        url = f"{API_SERVER_URL.rstrip('/')}/api/bans"
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
    async def rban(self, ctx: commands.Context, *, roblox_username: str):
        """Ban a Roblox user by their username. Usage: .rban <username>"""

        await ctx.message.delete()
        status_msg = await ctx.send(f"🔍 Looking up Roblox user **{roblox_username}**...")

        roblox_id, exact_name = await self.get_roblox_id(roblox_username)

        if roblox_id is None:
            await status_msg.edit(content=f"❌ No Roblox account found for **{roblox_username}**.")
            return

        success = await self.queue_ban(roblox_id, exact_name)

        if success:
            await status_msg.edit(
                content=(
                    f"✅ **{exact_name}** has been added to the ban queue.\n"
                    f"The ban will be applied next time a game server is running.\n"
                    f"*(Queued by {ctx.author.mention})*"
                )
            )
        else:
            await status_msg.edit(
                content=(
                    f"❌ Found **{exact_name}** but failed to queue the ban. "
                    "Check that your API server is running and the shared secret matches."
                )
            )

    @rban.error
    async def rban_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Usage: `.rban <roblox_username>`")
        elif isinstance(error, commands.CheckFailure):
            await ctx.send("❌ You don't have permission to use this command.")


async def setup(bot: commands.Bot):
    await bot.add_cog(RobloxBan(bot))
