"""
Modmail Plugin: Roblox Moderation
===================================
Commands:
  .rban   <roblox_username> <reason>
  .runban <roblox_username>
  .rlookup <roblox_username>
"""

import json
import aiohttp
import discord
from discord.ext import commands
from core import checks
from core.models import PermissionLevel

ROBLOX_API_KEY = "PASTE_YOUR_OPEN_CLOUD_API_KEY_HERE"
ROBLOX_UNIVERSE_ID = "PASTE_YOUR_UNIVERSE_ID_HERE"

DATASTORE_NAME = "PlayerData"
DIAMONDS_FIELD = "Diamonds"
DIAMONDS_KEY_PREFIX = ""

LOG_CHANNEL_NAME = "roblox-mod-logs"

_OC_BASE = "https://apis.roblox.com/cloud/v2"
_DS_BASE = "https://apis.roblox.com/datastores/v1"


class RobloxMod(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log_channel = None

    async def cog_load(self):
        await self.bot.wait_until_ready()
        guild = self.bot.guild
        if not guild:
            return

        existing = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
        if existing:
            self.log_channel = existing
        else:
            try:
                self.log_channel = await guild.create_text_channel(
                    name=LOG_CHANNEL_NAME
                )
            except discord.Forbidden:
                pass

    async def send_log(self, embed):
        if self.log_channel:
            await self.log_channel.send(embed=embed)

    async def get_roblox_id(self, username):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://users.roblox.com/v1/usernames/users",
                json={"usernames": [username], "excludeBannedUsers": False},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    users = data.get("data", [])
                    if users:
                        return int(users[0]["id"]), users[0]["name"]
        return None, None

    def _oc_headers(self):
        return {"x-api-key": ROBLOX_API_KEY, "Content-Type": "application/json"}

    # ───────────── BAN ─────────────

    @commands.command()
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def rban(self, ctx, *, args=""):
        await ctx.message.delete()

        parts = args.split(" ", 1)
        if len(parts) < 2:
            return await ctx.send("Usage: `.rban <username> <reason>`")

        username, reason = parts

        msg = await ctx.send(f"Looking up {username}...")
        user_id, exact = await self.get_roblox_id(username)

        if not user_id:
            return await msg.edit(content="User not found.")

        url = f"{_OC_BASE}/universes/{ROBLOX_UNIVERSE_ID}/user-restrictions/{user_id}"

        payload = {
            "gameJoinRestriction": {
                "active": True,
                "duration": "0s",
                "privateReason": reason,
                "displayReason": "You are banned.",
                "excludeAltAccounts": False,
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=self._oc_headers(), json=payload) as r:
                if r.status == 200:
                    await msg.edit(content=f"Banned {exact}")
                else:
                    await msg.edit(content="Ban failed.")

    # ───────────── UNBAN ─────────────

    @commands.command()
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def runban(self, ctx, *, username=""):
        await ctx.message.delete()

        msg = await ctx.send(f"Looking up {username}...")
        user_id, exact = await self.get_roblox_id(username)

        if not user_id:
            return await msg.edit(content="User not found.")

        url = f"{_OC_BASE}/universes/{ROBLOX_UNIVERSE_ID}/user-restrictions/{user_id}"

        payload = {"gameJoinRestriction": {"active": False}}

        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=self._oc_headers(), json=payload) as r:
                if r.status == 200:
                    await msg.edit(content=f"Unbanned {exact}")
                else:
                    await msg.edit(content="Unban failed.")

    # ───────────── LOOKUP ─────────────

    @commands.command()
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def rlookup(self, ctx, *, username=""):
        await ctx.message.delete()

        msg = await ctx.send(f"Looking up {username}...")
        user_id, exact = await self.get_roblox_id(username)

        if not user_id:
            return await msg.edit(content="User not found.")

        async with aiohttp.ClientSession() as session:

            user_resp = await session.get(f"https://users.roblox.com/v1/users/{user_id}")
            user_data = await user_resp.json()

            friends_resp = await session.get(
                f"https://friends.roblox.com/v1/users/{user_id}/friends/count"
            )
            friends_data = await friends_resp.json()

            # SAFE badge count (no crashes)
            badge_count = 0
            try:
                badges_resp = await session.get(
                    f"https://badges.roblox.com/v1/users/{user_id}/badges?limit=10"
                )
                if badges_resp.status == 200:
                    data = await badges_resp.json()
                    for b in data.get("data", []):
                        if b.get("awardingUniverse"):
                            if str(b["awardingUniverse"]["id"]) == str(ROBLOX_UNIVERSE_ID):
                                badge_count += 1
            except:
                pass

        embed = discord.Embed(title=exact)
        embed.add_field(name="User ID", value=user_id)
        embed.add_field(name="Friends", value=friends_data.get("count", 0))
        embed.add_field(name="Badges", value=badge_count)

        await msg.edit(content=None, embed=embed)


async def setup(bot):
    await bot.add_cog(RobloxMod(bot))
