"""
Modmail Plugin: Roblox Ban
===========================
Adds a command that lets moderators ban a Roblox user directly by username.

Usage (in Discord):
  .rban <roblox_username>
  Example: .rban xxleoncakewoofxx

SETUP:
  1. Place this folder (roblox_ban/) inside your Modmail bot's `plugins/` directory.
  2. Fill in the two configuration values below.
  3. Restart your bot.

HOW TO GET THE VALUES:
  - ROBLOX_API_KEY     : https://create.roblox.com/dashboard/credentials
                         Create a key with "User Restrictions" write permission
  - ROBLOX_UNIVERSE_ID : Open your game on create.roblox.com — the number in the URL

Permissions: only users with Moderator level or above in the Modmail bot can use .rban.
"""

import aiohttp
import discord
from discord.ext import commands
from core import checks
from core.models import PermissionLevel

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

ROBLOX_API_KEY     = "PASTE_YOUR_ROBLOX_OPEN_CLOUD_API_KEY_HERE"
ROBLOX_UNIVERSE_ID = "7243409883"   # e.g. "123456789"

BAN_DISPLAY_REASON  = "Banned by server moderation."
BAN_PRIVATE_REASON  = "Issued via Discord moderation command."

# ──────────────────────────────────────────────────────────────────────────────


class RobloxBan(commands.Cog):
    """Lets moderators ban Roblox users directly by username."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------
    # Roblox: look up user ID from a username
    # ------------------------------------------------------------------

    async def get_roblox_id(self, username: str) -> tuple[int, str] | tuple[None, None]:
        """
        Returns (roblox_id, exact_username) for the given username,
        or (None, None) if the account doesn't exist.
        """
        url = "https://users.roblox.com/v1/usernames/users"
        payload = {"usernames": [username], "excludeBannedUsers": False}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    users = data.get("data", [])
                    if users:
                        user = users[0]
                        return int(user["id"]), user["name"]
                    return None, None
                else:
                    return None, None

    # ------------------------------------------------------------------
    # Roblox Open Cloud: ban the user from the game
    # ------------------------------------------------------------------

    async def ban_roblox_user(self, roblox_user_id: int) -> bool:
        """
        Issues a permanent game ban for the given Roblox user ID.
        Returns True on success, False on failure.
        """
        url = (
            f"https://apis.roblox.com/cloud/v2/universes/"
            f"{ROBLOX_UNIVERSE_ID}/user-restrictions/{roblox_user_id}"
        )
        headers = {
            "x-api-key": ROBLOX_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "gameJoinRestriction": {
                "active": True,
                "duration": None,
                "privateReason": BAN_PRIVATE_REASON,
                "displayReason": BAN_DISPLAY_REASON,
                "excludeAltAccounts": False,
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=headers, json=payload) as resp:
                return resp.status in (200, 204)

    # ------------------------------------------------------------------
    # Command: .rban <roblox_username>
    # ------------------------------------------------------------------

    @commands.command(name="rban")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def rban(self, ctx: commands.Context, *, roblox_username: str):
        """Ban a Roblox user by their username. Usage: .rban <username>"""

        await ctx.message.delete()

        status_msg = await ctx.send(
            f"🔍 Looking up Roblox user **{roblox_username}**..."
        )

        roblox_id, exact_name = await self.get_roblox_id(roblox_username)

        if roblox_id is None:
            await status_msg.edit(
                content=f"❌ No Roblox account found for **{roblox_username}**."
            )
            return

        success = await self.ban_roblox_user(roblox_id)

        if success:
            await status_msg.edit(
                content=(
                    f"✅ **{exact_name}** has been banned from the Roblox game.\n"
                    f"*(Banned by {ctx.author.mention})*"
                )
            )
            print(
                f"[RobloxBan] {ctx.author} banned Roblox user "
                f"{exact_name} (ID: {roblox_id})."
            )
        else:
            await status_msg.edit(
                content=(
                    f"❌ Found **{exact_name}** but failed to ban them. "
                    "Check that your Roblox API key has the correct permissions."
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
