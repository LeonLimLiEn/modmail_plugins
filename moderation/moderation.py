import discord
from discord.ext import commands
import aiohttp
import json
import os
from datetime import datetime, timezone
from core import checks
from core.models import PermissionLevel

# ============================================================
# CREDENTIALS — fill these in before running
# ============================================================
ROBLOX_OPEN_CLOUD_API_KEY = "YOUR_OPEN_CLOUD_API_KEY_HERE"
ROBLOX_UNIVERSE_ID        = "YOUR_UNIVERSE_ID_HERE"
LOG_CHANNEL_ID            = 000000000000000000   # paste your log channel ID here
# ============================================================

BANS_FILE = os.path.join(os.path.dirname(__file__), "roblox_bans.json")


def load_bans() -> dict:
    if os.path.exists(BANS_FILE):
        with open(BANS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_bans(bans: dict) -> None:
    with open(BANS_FILE, "w") as f:
        json.dump(bans, f, indent=2)


async def fetch_roblox_user_by_username(session: aiohttp.ClientSession, username: str) -> dict | None:
    url = "https://users.roblox.com/v1/usernames/users"
    payload = {"usernames": [username], "excludeBannedUsers": False}
    async with session.post(url, json=payload) as resp:
        if resp.status == 200:
            data = await resp.json()
            if data.get("data"):
                return data["data"][0]
    return None


async def fetch_roblox_user_by_id(session: aiohttp.ClientSession, user_id: int) -> dict | None:
    url = f"https://users.roblox.com/v1/users/{user_id}"
    async with session.get(url) as resp:
        if resp.status == 200:
            return await resp.json()
    return None


async def fetch_roblox_avatar(session: aiohttp.ClientSession, user_id: int) -> str | None:
    url = (
        f"https://thumbnails.roblox.com/v1/users/avatar-headshot"
        f"?userIds={user_id}&size=420x420&format=Png"
    )
    async with session.get(url) as resp:
        if resp.status == 200:
            data = await resp.json()
            if data.get("data"):
                return data["data"][0].get("imageUrl")
    return None


async def resolve_user(identifier: str) -> tuple[dict | None, str | None]:
    async with aiohttp.ClientSession() as session:
        if identifier.isdigit():
            user = await fetch_roblox_user_by_id(session, int(identifier))
            if user:
                avatar = await fetch_roblox_avatar(session, user["id"])
                return user, avatar
        else:
            basic = await fetch_roblox_user_by_username(session, identifier)
            if basic:
                user = await fetch_roblox_user_by_id(session, basic["id"])
                if user:
                    avatar = await fetch_roblox_avatar(session, user["id"])
                    return user, avatar
    return None, None


def format_roblox_date(raw: str) -> str:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%B %d, %Y")
    except Exception:
        return raw


def not_found_embed(identifier: str) -> discord.Embed:
    return discord.Embed(
        description=f"❌ No Roblox user found for `{identifier}`.",
        color=discord.Color.red(),
    )


class RobloxModeration(commands.Cog):
    """Roblox in-game moderation commands."""

    def __init__(self, bot):
        self.bot = bot

    async def _log(self, embed: discord.Embed) -> None:
        if not LOG_CHANNEL_ID:
            return
        channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed)

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(
                description=f"❌ You need to provide a username or user ID.\nUsage: `?{ctx.command.name} <username or user ID>`",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)
        else:
            raise error

    # ------------------------------------------------------------------ rlookup

    @commands.command(name="rlookup")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def rlookup(self, ctx: commands.Context, *, identifier: str):
        """Look up a Roblox user by username or user ID.

        Shows their profile, account info, and whether they are banned in-game.

        Usage: ?rlookup <username or user ID>
        """
        async with ctx.typing():
            user, avatar = await resolve_user(identifier)
            if not user:
                return await ctx.send(embed=not_found_embed(identifier))

            bans = load_bans()
            uid = str(user["id"])
            is_banned = uid in bans
            ban_info = bans.get(uid, {})

            description = (user.get("description") or "").strip() or "No description."
            if len(description) > 350:
                description = description[:347] + "..."

            created = format_roblox_date(user.get("created", "Unknown"))
            display = user.get("displayName") or user["name"]

            embed = discord.Embed(
                title=f"Roblox Profile — {user['name']}",
                url=f"https://www.roblox.com/users/{user['id']}/profile",
                color=discord.Color.red() if is_banned else discord.Color.brand_green(),
            )
            if avatar:
                embed.set_thumbnail(url=avatar)

            embed.add_field(name="Username", value=f"`{user['name']}`", inline=True)
            embed.add_field(name="Display Name", value=f"`{display}`", inline=True)
            embed.add_field(name="User ID", value=f"`{user['id']}`", inline=True)
            embed.add_field(name="Account Created", value=created, inline=True)
            embed.add_field(
                name="Game Ban Status",
                value="🔴 **BANNED**" if is_banned else "🟢 **Not Banned**",
                inline=True,
            )

            if is_banned:
                embed.add_field(
                    name="Ban Reason",
                    value=ban_info.get("reason", "No reason provided"),
                    inline=False,
                )
                embed.add_field(
                    name="Banned By",
                    value=ban_info.get("banned_by", "Unknown"),
                    inline=True,
                )
                embed.add_field(
                    name="Banned On",
                    value=ban_info.get("banned_at", "Unknown"),
                    inline=True,
                )

            if description != "No description.":
                embed.add_field(name="Bio", value=description, inline=False)

            embed.set_footer(text=f"Requested by {ctx.author}")
            await ctx.send(embed=embed)

    # -------------------------------------------------------------------- rban

    @commands.command(name="rban")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def rban(self, ctx: commands.Context, identifier: str, *, reason: str = "No reason provided"):
        """Ban a Roblox user from the game.

        Usage: ?rban <username or user ID> [reason]
        """
        async with ctx.typing():
            user, avatar = await resolve_user(identifier)
            if not user:
                return await ctx.send(embed=not_found_embed(identifier))

            bans = load_bans()
            uid = str(user["id"])

            if uid in bans:
                embed = discord.Embed(
                    description=(
                        f"⚠️ **{user['name']}** (`{user['id']}`) is already banned.\n"
                        f"Reason on file: *{bans[uid].get('reason', 'None')}*"
                    ),
                    color=discord.Color.orange(),
                )
                return await ctx.send(embed=embed)

            timestamp = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
            bans[uid] = {
                "username": user["name"],
                "reason": reason,
                "banned_by": str(ctx.author),
                "banned_at": timestamp,
            }
            save_bans(bans)

            embed = discord.Embed(title="🔨 Roblox Ban Issued", color=discord.Color.red())
            if avatar:
                embed.set_thumbnail(url=avatar)
            embed.add_field(
                name="User",
                value=f"**{user['name']}** (`{user['id']}`)\n[View Profile](https://www.roblox.com/users/{user['id']}/profile)",
                inline=False,
            )
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.add_field(name="Banned By", value=str(ctx.author), inline=True)
            embed.add_field(name="Time", value=timestamp, inline=True)
            embed.set_footer(text=f"Use ?runban {user['id']} to reverse this")
            await ctx.send(embed=embed)
            await self._log(embed)

    # ------------------------------------------------------------------ runban

    @commands.command(name="runban")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def runban(self, ctx: commands.Context, identifier: str):
        """Unban a Roblox user from the game.

        Usage: ?runban <username or user ID>
        """
        async with ctx.typing():
            user, avatar = await resolve_user(identifier)
            if not user:
                return await ctx.send(embed=not_found_embed(identifier))

            bans = load_bans()
            uid = str(user["id"])

            if uid not in bans:
                embed = discord.Embed(
                    description=f"⚠️ **{user['name']}** (`{user['id']}`) is not currently banned.",
                    color=discord.Color.orange(),
                )
                return await ctx.send(embed=embed)

            del bans[uid]
            save_bans(bans)

            embed = discord.Embed(title="✅ Ban Removed", color=discord.Color.brand_green())
            if avatar:
                embed.set_thumbnail(url=avatar)
            embed.add_field(
                name="User",
                value=f"**{user['name']}** (`{user['id']}`)\n[View Profile](https://www.roblox.com/users/{user['id']}/profile)",
                inline=False,
            )
            embed.add_field(name="Unbanned By", value=str(ctx.author), inline=True)
            embed.add_field(
                name="Time",
                value=datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC"),
                inline=True,
            )
            await ctx.send(embed=embed)
            await self._log(embed)

    # ------------------------------------------------------------------- rkick

    @commands.command(name="rkick")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def rkick(self, ctx: commands.Context, identifier: str, *, reason: str = "No reason provided"):
        """Log a kick action for a Roblox user.

        Usage: ?rkick <username or user ID> [reason]
        """
        async with ctx.typing():
            user, avatar = await resolve_user(identifier)
            if not user:
                return await ctx.send(embed=not_found_embed(identifier))

            timestamp = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")

            embed = discord.Embed(title="👢 Roblox Kick Logged", color=discord.Color.orange())
            if avatar:
                embed.set_thumbnail(url=avatar)
            embed.add_field(
                name="User",
                value=f"**{user['name']}** (`{user['id']}`)\n[View Profile](https://www.roblox.com/users/{user['id']}/profile)",
                inline=False,
            )
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.add_field(name="Kicked By", value=str(ctx.author), inline=True)
            embed.add_field(name="Time", value=timestamp, inline=True)
            embed.set_footer(text="Apply this kick in-game — use ?rban to make it permanent")
            await ctx.send(embed=embed)
            await self._log(embed)


async def setup(bot):
    await bot.add_cog(RobloxModeration(bot))
