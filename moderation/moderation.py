import json
import aiohttp
import discord
from discord.ext import commands
from core import checks
from core.models import PermissionLevel

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

# Roblox Open Cloud (bans, unbans, DataStore lookups)
ROBLOX_API_KEY      = "PASTE_YOUR_OPEN_CLOUD_API_KEY_HERE"
ROBLOX_UNIVERSE_ID  = "PASTE_YOUR_UNIVERSE_ID_HERE"

# DataStore config for diamond lookup
DATASTORE_NAME      = "PlayerData"   # your DataStore name
DIAMONDS_FIELD      = "Diamonds"     # field inside the saved table (or None if stored directly)
DIAMONDS_KEY_PREFIX = ""             # prefix before userId, e.g. "Player_" → key = "Player_12345"

# Discord log channel
LOG_CHANNEL_NAME = "roblox-mod-logs"

# Open Cloud base URL
_OC_BASE = "https://apis.roblox.com/cloud/v2"
_DS_BASE = "https://apis.roblox.com/datastores/v1"

# ──────────────────────────────────────────────────────────────────────────────


class RobloxMod(commands.Cog):
    """Lets moderators moderate Roblox users directly from Discord."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log_channel: discord.TextChannel | None = None

    async def cog_load(self):
        """Finds or creates the mod-log channel on startup."""
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
                print(f"[RobloxMod] Created log channel: #{LOG_CHANNEL_NAME}")
            except discord.Forbidden:
                print(f"[RobloxMod] Missing permissions to create #{LOG_CHANNEL_NAME}.")

    async def send_log(self, embed: discord.Embed):
        if self.log_channel:
            await self.log_channel.send(embed=embed)

    async def get_roblox_id(self, username: str) -> tuple:
        """Returns (userId, exactName) or (None, None)."""
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

    # ── .rban ─────────────────────────────────────────────────────────────────

    @commands.command(name="rban")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def rban(self, ctx: commands.Context, *, args: str = ""):
        """Ban a Roblox user via Open Cloud API. Usage: .rban <username> <reason>"""

        await ctx.message.delete()

        parts = args.strip().split(" ", 1)
        roblox_username = parts[0] if len(parts) >= 1 else ""
        reason = parts[1] if len(parts) >= 2 else ""

        if not roblox_username:
            embed = discord.Embed(title="⚠️ Missing Information", color=discord.Color.orange())
            embed.add_field(name="Usage",   value="`.rban <roblox_username> <reason>`",           inline=False)
            embed.add_field(name="Example", value="`.rban xxleoncakewoofxx Exploiting in game`",  inline=False)
            await ctx.send(embed=embed)
            return

        if not reason:
            embed = discord.Embed(title="⚠️ Missing Reason", color=discord.Color.orange())
            embed.description = f"Please provide a reason for banning **{roblox_username}**."
            embed.add_field(name="Usage", value="`.rban <roblox_username> <reason>`", inline=False)
            await ctx.send(embed=embed)
            return

        status_msg = await ctx.send(f"🔍 Looking up **{roblox_username}**...")
        roblox_id, exact_name = await self.get_roblox_id(roblox_username)

        if roblox_id is None:
            embed = discord.Embed(title="❌ User Not Found", color=discord.Color.red())
            embed.description = f"No Roblox account found for **{roblox_username}**."
            await status_msg.edit(content=None, embed=embed)
            return

        await status_msg.edit(content=f"⏳ Banning **{exact_name}**...")

        url = f"{_OC_BASE}/universes/{ROBLOX_UNIVERSE_ID}/user-restrictions/{roblox_id}"
        payload = {
            "gameJoinRestriction": {
                "active": True,
                "duration": "0s",
                "privateReason": reason,
                "displayReason": "You have been banned from this experience.",
                "excludeAltAccounts": False,
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=self._oc_headers(), json=payload) as resp:
                success = resp.status == 200
                error_body = await resp.text() if not success else ""

        if success:
            embed = discord.Embed(title="🔨 Player Banned", color=discord.Color.red())
            embed.add_field(name="Roblox Username", value=exact_name, inline=True)
            embed.add_field(name="User ID",         value=str(roblox_id), inline=True)
            embed.add_field(name="Reason",          value=reason, inline=False)
            embed.set_footer(text=f"Banned by {ctx.author.display_name}")
            await status_msg.edit(content=None, embed=embed)
            await self.send_log(embed)
        else:
            embed = discord.Embed(title="❌ Ban Failed", color=discord.Color.red())
            embed.description = (
                f"Could not ban **{exact_name}**.\n"
                f"Check your API key has `user-restrictions:write` permission and your Universe ID is correct.\n"
                f"```{error_body[:300]}```"
            )
            await status_msg.edit(content=None, embed=embed)

    @rban.error
    async def rban_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
            await ctx.send("❌ You don't have permission to use this command.")

    # ── .runban ───────────────────────────────────────────────────────────────

    @commands.command(name="runban")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def runban(self, ctx: commands.Context, *, roblox_username: str = ""):
        """Unban a Roblox user via Open Cloud API. Usage: .runban <username>"""

        await ctx.message.delete()

        if not roblox_username:
            embed = discord.Embed(title="⚠️ Missing Username", color=discord.Color.orange())
            embed.add_field(name="Usage",   value="`.runban <roblox_username>`",  inline=False)
            embed.add_field(name="Example", value="`.runban xxleoncakewoofxx`",   inline=False)
            await ctx.send(embed=embed)
            return

        status_msg = await ctx.send(f"🔍 Looking up **{roblox_username}**...")
        roblox_id, exact_name = await self.get_roblox_id(roblox_username)

        if roblox_id is None:
            embed = discord.Embed(title="❌ User Not Found", color=discord.Color.red())
            embed.description = f"No Roblox account found for **{roblox_username}**."
            await status_msg.edit(content=None, embed=embed)
            return

        await status_msg.edit(content=f"⏳ Unbanning **{exact_name}**...")

        url = f"{_OC_BASE}/universes/{ROBLOX_UNIVERSE_ID}/user-restrictions/{roblox_id}"
        payload = {"gameJoinRestriction": {"active": False}}

        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=self._oc_headers(), json=payload) as resp:
                success = resp.status == 200
                error_body = await resp.text() if not success else ""

        if success:
            embed = discord.Embed(title="✅ Player Unbanned", color=discord.Color.green())
            embed.add_field(name="Roblox Username", value=exact_name, inline=True)
            embed.add_field(name="User ID",         value=str(roblox_id), inline=True)
            embed.set_footer(text=f"Unbanned by {ctx.author.display_name}")
            await status_msg.edit(content=None, embed=embed)
            await self.send_log(embed)
        else:
            embed = discord.Embed(title="❌ Unban Failed", color=discord.Color.red())
            embed.description = (
                f"Could not unban **{exact_name}**.\n"
                f"```{error_body[:300]}```"
            )
            await status_msg.edit(content=None, embed=embed)

    @runban.error
    async def runban_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
            await ctx.send("❌ You don't have permission to use this command.")

    # ── .rlookup ──────────────────────────────────────────────────────────────

    @commands.command(name="rlookup")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def rlookup(self, ctx: commands.Context, *, roblox_username: str = ""):
        """Look up a Roblox user's profile and in-game data. Usage: .rlookup <username>"""

        await ctx.message.delete()

        if not roblox_username:
            embed = discord.Embed(title="⚠️ Missing Username", color=discord.Color.orange())
            embed.add_field(name="Usage", value="`.rlookup <roblox_username>`", inline=False)
            await ctx.send(embed=embed)
            return

        from datetime import datetime

        status_msg = await ctx.send(f"🔍 Looking up **{roblox_username}**...")
        roblox_id, exact_name = await self.get_roblox_id(roblox_username)

        if roblox_id is None:
            embed = discord.Embed(title="❌ User Not Found", color=discord.Color.red())
            embed.description = f"No Roblox account found for **{roblox_username}**."
            await status_msg.edit(content=None, embed=embed)
            return

        # Build DataStore key
        ds_key = f"{DIAMONDS_KEY_PREFIX}{roblox_id}"

        async with aiohttp.ClientSession() as session:
            # Public profile
            user_resp = await session.get(f"https://users.roblox.com/v1/users/{roblox_id}")
            user_data = await user_resp.json() if user_resp.status == 200 else {}

            # Avatar headshot
            avatar_resp = await session.get(
                f"https://thumbnails.roblox.com/v1/users/avatar-headshot"
                f"?userIds={roblox_id}&size=150x150&format=Png&isCircular=false"
            )
            avatar_data = await avatar_resp.json() if avatar_resp.status == 200 else {}

            # Friend count
            friends_resp = await session.get(
                f"https://friends.roblox.com/v1/users/{roblox_id}/friends/count"
            )
            friends_data = await friends_resp.json() if friends_resp.status == 200 else {}

            # Badge count
            badges_resp = await session.get(
                f"https://badges.roblox.com/v1/users/{roblox_id}/badges?limit=1"
            )
            badges_data = await badges_resp.json() if badges_resp.status == 200 else {}

            # DataStore — diamonds via Open Cloud
            diamonds = None
            ds_url = (
                f"{_DS_BASE}/universes/{ROBLOX_UNIVERSE_ID}"
                f"/standard-datastores/datastore/entries/entry"
                f"?datastoreName={DATASTORE_NAME}&entryKey={ds_key}"
            )
            ds_resp = await session.get(ds_url, headers={"x-api-key": ROBLOX_API_KEY})
            if ds_resp.status == 200:
                raw = await ds_resp.text()
                try:
                    parsed = json.loads(raw)
                    if DIAMONDS_FIELD and isinstance(parsed, dict):
                        diamonds = parsed.get(DIAMONDS_FIELD)
                    else:
                        diamonds = parsed
                except Exception:
                    diamonds = None

        display_name = user_data.get("displayName", exact_name)
        description  = user_data.get("description", "") or ""
        created_raw  = user_data.get("created", "")
        is_banned    = user_data.get("isBanned", False)
        friend_count = friends_data.get("count", "N/A")
        badge_count  = badges_data.get("total", "N/A")

        join_date = "Unknown"
        if created_raw:
            try:
                dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                join_date = dt.strftime("%B %d, %Y")
            except Exception:
                join_date = created_raw[:10]

        avatar_url = None
        try:
            avatar_url = avatar_data["data"][0]["imageUrl"]
        except (KeyError, IndexError):
            pass

        embed = discord.Embed(
            title=f"{'🔨 ' if is_banned else ''}@{exact_name}",
            url=f"https://www.roblox.com/users/{roblox_id}/profile",
            color=discord.Color.red() if is_banned else discord.Color.blurple(),
        )
        embed.add_field(name="Display Name",  value=display_name,                 inline=True)
        embed.add_field(name="User ID",       value=str(roblox_id),               inline=True)
        embed.add_field(name="Joined Roblox", value=join_date,                    inline=True)
        embed.add_field(name="Friends",       value=str(friend_count),            inline=True)
        embed.add_field(name="Badges",        value=str(badge_count),             inline=True)
        embed.add_field(name="Roblox Banned", value="Yes" if is_banned else "No", inline=True)

        if diamonds is not None:
            embed.add_field(name="💎 Diamonds", value=f"{int(diamonds):,}", inline=True)
        else:
            embed.add_field(name="💎 Diamonds", value="Not found — check DATASTORE_NAME and DIAMONDS_FIELD in the plugin config.", inline=False)

        if description:
            embed.add_field(name="About", value=description[:256], inline=False)

        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        embed.set_footer(text=f"Looked up by {ctx.author.display_name}")
        await status_msg.edit(content=None, embed=embed)

    @rlookup.error
    async def rlookup_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
            await ctx.send("❌ You don't have permission to use this command.")


async def setup(bot: commands.Bot):
    await bot.add_cog(RobloxMod(bot))
