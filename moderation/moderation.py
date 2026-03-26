"""
Modmail Plugin: Roblox Moderation
===================================
Commands:
  .rban <roblox_username> <reason> — ban a Roblox user (instant, via Open Cloud API)
  .runban <roblox_username> — unban a Roblox user (instant, via Open Cloud API)
  .rlookup <roblox_username> — look up profile + in-game diamonds
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
                    name=LOG_CHANNEL_NAME,
                    topic="Roblox moderation logs — bans, unbans, and kicks.",
                )
            except discord.Forbidden:
                pass

    async def send_log(self, embed):
        if self.log_channel:
            await self.log_channel.send(embed=embed)

    async def get_roblox_id(self, username: str):
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

    # ── RBAN ──
    @commands.command(name="rban")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def rban(self, ctx, *, args=""):
        await ctx.message.delete()

        parts = args.strip().split(" ", 1)
        roblox_username = parts[0] if len(parts) >= 1 else ""
        reason = parts[1] if len(parts) >= 2 else ""

        if not roblox_username:
            return await ctx.send("Usage: .rban <username> <reason>")
        if not reason:
            return await ctx.send("Please provide a reason.")

        msg = await ctx.send(f"Looking up {roblox_username}...")
        roblox_id, exact_name = await self.get_roblox_id(roblox_username)

        if roblox_id is None:
            return await msg.edit(content="User not found.")

        url = f"{_OC_BASE}/universes/{ROBLOX_UNIVERSE_ID}/user-restrictions/{roblox_id}"

        payload = {
            "gameJoinRestriction": {
                "active": True,
                "duration": "0s",
                "privateReason": reason,
                "displayReason": "You have been banned.",
                "excludeAltAccounts": False,
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=self._oc_headers(), json=payload) as resp:
                if resp.status == 200:
                    await msg.edit(content=f"Banned {exact_name}")
                else:
                    await msg.edit(content="Ban failed.")

    # ── RUNBAN ──
    @commands.command(name="runban")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def runban(self, ctx, *, roblox_username=""):
        await ctx.message.delete()

        msg = await ctx.send(f"Looking up {roblox_username}...")
        roblox_id, exact_name = await self.get_roblox_id(roblox_username)

        if roblox_id is None:
            return await msg.edit(content="User not found.")

        url = f"{_OC_BASE}/universes/{ROBLOX_UNIVERSE_ID}/user-restrictions/{roblox_id}"
        payload = {"gameJoinRestriction": {"active": False}}

        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=self._oc_headers(), json=payload) as resp:
                if resp.status == 200:
                    await msg.edit(content=f"Unbanned {exact_name}")
                else:
                    await msg.edit(content="Unban failed.")

    # ── RLOOKUP ──
    @commands.command(name="rlookup")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def rlookup(self, ctx, *, roblox_username=""):
        await ctx.message.delete()

        msg = await ctx.send(f"Looking up {roblox_username}...")
        roblox_id, exact_name = await self.get_roblox_id(roblox_username)

        if roblox_id is None:
            return await msg.edit(content="User not found.")

        async with aiohttp.ClientSession() as session:

            user_resp = await session.get(f"https://users.roblox.com/v1/users/{roblox_id}")
            user_data = await user_resp.json()

            friends_resp = await session.get(
                f"https://friends.roblox.com/v1/users/{roblox_id}/friends/count"
            )
            friends_data = await friends_resp.json()

            badge_count = 0
            cursor = None

            while True:
                url = f"https://badges.roblox.com/v1/users/{roblox_id}/badges?limit=100"
                if cursor:
                    url += f"&cursor={cursor}"

                badges_resp = await session.get(url)
                if badges_resp.status != 200:
                    break

                data = await badges_resp.json()

                for badge in data.get("data", []):
                    universe = badge.get("awardingUniverse")
                    if universe and str(universe.get("id")) == str(ROBLOX_UNIVERSE_ID):
                        badge_count += 1

                cursor = data.get("nextPageCursor")
                if not cursor:
                    break

        embed = discord.Embed(title=exact_name)
        embed.add_field(name="User ID", value=roblox_id)
        embed.add_field(name="Friends", value=friends_data.get("count", 0))
        embed.add_field(name="Badges", value=badge_count)

        await msg.edit(content=None, embed=embed)


async def setup(bot):
    await bot.add_cog(RobloxMod(bot))
