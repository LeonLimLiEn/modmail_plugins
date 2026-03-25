"""
Modmail Plugin: Roblox Ban
===========================
Commands:
  .rban <roblox_username> <reason>   — ban a Roblox user
  .runban <roblox_username>          — unban a Roblox user
  .rkick <roblox_username> <reason>  — kick a Roblox user from the game

Examples:
  .rban xxleoncakewoofxx Exploiting in game
  .runban xxleoncakewoofxx
  .rkick xxleoncakewoofxx Breaking rules

SETUP:
  1. Drop this file into your Modmail bot's `plugins/` directory.
  2. Fill in the two configuration values below.
  3. Restart your bot.

Permissions: only users with Moderator level or above in Modmail can use these commands.
"""

import aiohttp
import discord
from discord.ext import commands
from core import checks
from core.models import PermissionLevel

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

API_SERVER_URL = "https://roblox-ban-server-cpca.onrender.com"
SHARED_SECRET  = "EMAdabest"  # must match the value in server.py
LOG_CHANNEL_ID = 1484510887694958622  # paste your log channel ID here, e.g. 1234567890123456789
                    # right-click the channel in Discord > Copy Channel ID
                    # (enable Developer Mode in Discord settings first)

# ──────────────────────────────────────────────────────────────────────────────


class RobloxBan(commands.Cog):
    """Lets moderators ban/unban Roblox users directly by username."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def send_log(self, embed: discord.Embed):
        """Send a log embed to the configured log channel."""
        if not LOG_CHANNEL_ID:
            return
        channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed)

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

    async def queue_action(self, endpoint: str, roblox_user_id: int, roblox_username: str) -> bool:
        """Post a ban or unban to the API server. Returns True on success."""
        url = f"{API_SERVER_URL.rstrip('/')}/{endpoint}"
        payload = {
            "robloxUserId": roblox_user_id,
            "robloxUsername": roblox_username,
            "secret": SHARED_SECRET,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                return resp.status == 201

    # ── .rban ────────────────────────────────────────────────────────────────

    @commands.command(name="rban")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def rban(self, ctx: commands.Context, *, args: str = ""):
        """Ban a Roblox user. Usage: .rban <username> <reason>"""

        await ctx.message.delete()

        parts = args.strip().split(" ", 1)
        roblox_username = parts[0] if len(parts) >= 1 else ""
        reason = parts[1] if len(parts) >= 2 else ""

        if not roblox_username and not reason:
            embed = discord.Embed(title="⚠️ Missing Information", color=discord.Color.orange())
            embed.description = "Please provide a Roblox username and a reason."
            embed.add_field(name="Usage", value="`.rban <roblox_username> <reason>`", inline=False)
            embed.add_field(name="Example", value="`.rban xxleoncakewoofxx Exploiting in game`", inline=False)
            await ctx.send(embed=embed)
            return

        if not roblox_username:
            embed = discord.Embed(title="⚠️ Missing Roblox Username", color=discord.Color.orange())
            embed.add_field(name="Usage", value="`.rban <roblox_username> <reason>`", inline=False)
            await ctx.send(embed=embed)
            return

        if not reason:
            embed = discord.Embed(title="⚠️ Missing Reason", color=discord.Color.orange())
            embed.description = f"Please provide a reason for banning **{roblox_username}**."
            embed.add_field(name="Usage", value="`.rban <roblox_username> <reason>`", inline=False)
            await ctx.send(embed=embed)
            return

        status_msg = await ctx.send(f"🔍 Looking up Roblox user **{roblox_username}**...")
        roblox_id, exact_name = await self.get_roblox_id(roblox_username)

        if roblox_id is None:
            embed = discord.Embed(title="❌ User Not Found", color=discord.Color.red())
            embed.description = f"No Roblox account found for **{roblox_username}**.\nDouble-check the username and try again."
            await status_msg.edit(content=None, embed=embed)
            return

        success = await self.queue_action("bans", roblox_id, exact_name)

        if success:
            embed = discord.Embed(title="🔨 Player Banned", color=discord.Color.red())
            embed.add_field(name="Roblox Username", value=exact_name, inline=True)
            embed.add_field(name="Reason", value=reason, inline=True)
            embed.add_field(name="Status", value="Ban queued — will be applied next time a game server is running.", inline=False)
            embed.set_footer(text=f"Banned by {ctx.author.display_name}")
            await status_msg.edit(content=None, embed=embed)
            await self.send_log(embed)
        else:
            embed = discord.Embed(title="❌ Failed to Queue Ban", color=discord.Color.red())
            embed.description = f"Found **{exact_name}** but couldn't reach the ban server.\nCheck that your server is running and the shared secret matches."
            await status_msg.edit(content=None, embed=embed)

    @rban.error
    async def rban_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CheckFailure):
            await ctx.send("❌ You don't have permission to use this command.")

    # ── .runban ──────────────────────────────────────────────────────────────

    @commands.command(name="runban")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def runban(self, ctx: commands.Context, *, roblox_username: str = ""):
        """Unban a Roblox user. Usage: .runban <username>"""

        await ctx.message.delete()

        if not roblox_username:
            embed = discord.Embed(title="⚠️ Missing Roblox Username", color=discord.Color.orange())
            embed.add_field(name="Usage", value="`.runban <roblox_username>`", inline=False)
            embed.add_field(name="Example", value="`.runban xxleoncakewoofxx`", inline=False)
            await ctx.send(embed=embed)
            return

        status_msg = await ctx.send(f"🔍 Looking up Roblox user **{roblox_username}**...")
        roblox_id, exact_name = await self.get_roblox_id(roblox_username)

        if roblox_id is None:
            embed = discord.Embed(title="❌ User Not Found", color=discord.Color.red())
            embed.description = f"No Roblox account found for **{roblox_username}**.\nDouble-check the username and try again."
            await status_msg.edit(content=None, embed=embed)
            return

        success = await self.queue_action("unbans", roblox_id, exact_name)

        if success:
            embed = discord.Embed(title="✅ Player Unbanned", color=discord.Color.green())
            embed.add_field(name="Roblox Username", value=exact_name, inline=True)
            embed.add_field(name="Status", value="Unban queued — will be applied next time a game server is running.", inline=False)
            embed.set_footer(text=f"Unbanned by {ctx.author.display_name}")
            await status_msg.edit(content=None, embed=embed)
            await self.send_log(embed)
        else:
            embed = discord.Embed(title="❌ Failed to Queue Unban", color=discord.Color.red())
            embed.description = f"Found **{exact_name}** but couldn't reach the ban server.\nCheck that your server is running and the shared secret matches."
            await status_msg.edit(content=None, embed=embed)

    @runban.error
    async def runban_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CheckFailure):
            await ctx.send("❌ You don't have permission to use this command.")

    # ── .rkick ───────────────────────────────────────────────────────────────

    @commands.command(name="rkick")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def rkick(self, ctx: commands.Context, *, args: str = ""):
        """Kick a Roblox user. Usage: .rkick <username> <reason>"""

        await ctx.message.delete()

        parts = args.strip().split(" ", 1)
        roblox_username = parts[0] if len(parts) >= 1 else ""
        reason = parts[1] if len(parts) >= 2 else ""

        if not roblox_username and not reason:
            embed = discord.Embed(title="⚠️ Missing Information", color=discord.Color.orange())
            embed.description = "Please provide a Roblox username and a reason."
            embed.add_field(name="Usage", value="`.rkick <roblox_username> <reason>`", inline=False)
            embed.add_field(name="Example", value="`.rkick xxleoncakewoofxx Breaking rules`", inline=False)
            await ctx.send(embed=embed)
            return

        if not roblox_username:
            embed = discord.Embed(title="⚠️ Missing Roblox Username", color=discord.Color.orange())
            embed.add_field(name="Usage", value="`.rkick <roblox_username> <reason>`", inline=False)
            await ctx.send(embed=embed)
            return

        if not reason:
            embed = discord.Embed(title="⚠️ Missing Reason", color=discord.Color.orange())
            embed.description = f"Please provide a reason for kicking **{roblox_username}**."
            embed.add_field(name="Usage", value="`.rkick <roblox_username> <reason>`", inline=False)
            await ctx.send(embed=embed)
            return

        status_msg = await ctx.send(f"🔍 Looking up Roblox user **{roblox_username}**...")
        roblox_id, exact_name = await self.get_roblox_id(roblox_username)

        if roblox_id is None:
            embed = discord.Embed(title="❌ User Not Found", color=discord.Color.red())
            embed.description = f"No Roblox account found for **{roblox_username}**.\nDouble-check the username and try again."
            await status_msg.edit(content=None, embed=embed)
            return

        url = f"{API_SERVER_URL.rstrip('/')}/kicks"
        payload = {
            "robloxUserId": roblox_id,
            "robloxUsername": exact_name,
            "reason": reason,
            "secret": SHARED_SECRET,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                success = resp.status == 201

        if success:
            embed = discord.Embed(title="👢 Player Kicked", color=discord.Color.orange())
            embed.add_field(name="Roblox Username", value=exact_name, inline=True)
            embed.add_field(name="Reason", value=reason, inline=True)
            embed.add_field(name="Note", value="Only kicks if the player is currently in a game server.", inline=False)
            embed.set_footer(text=f"Kicked by {ctx.author.display_name}")
            await status_msg.edit(content=None, embed=embed)
            await self.send_log(embed)
        else:
            embed = discord.Embed(title="❌ Failed to Queue Kick", color=discord.Color.red())
            embed.description = f"Found **{exact_name}** but couldn't reach the ban server."
            await status_msg.edit(content=None, embed=embed)

    @rkick.error
    async def rkick_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CheckFailure):
            await ctx.send("❌ You don't have permission to use this command.")


async def setup(bot: commands.Bot):
    await bot.add_cog(RobloxBan(bot))
