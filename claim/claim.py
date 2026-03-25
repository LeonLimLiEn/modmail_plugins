from discord.ext import commands
import aiohttp
import asyncio
import time
import discord

class Players(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.place_id = 7243409883  # Replace with your Roblox place ID

        # Cache
        self.cached_players = None
        self.last_fetch = 0
        self.cache_time = 15  # seconds

        self.session = None  # Will be created when needed

    async def ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def fetch_universe_id(self):
        await self.ensure_session()
        url = f"https://apis.roblox.com/universes/v1/places/{self.place_id}/universe"

        for _ in range(3):  # Retry 3 times
            try:
                async with self.session.get(url, timeout=10) as res:
                    if res.status == 200:
                        data = await res.json()
                        return data.get("universeId")
            except Exception:
                await asyncio.sleep(1)
        return None

    async def fetch_players(self):
        await self.ensure_session()
        universe_id = await self.fetch_universe_id()
        if not universe_id:
            return None

        url = f"https://games.roblox.com/v1/games?universeIds={universe_id}"

        for _ in range(3):  # Retry 3 times
            try:
                async with self.session.get(url, timeout=10) as res:
                    if res.status == 200:
                        data = await res.json()
                        return data["data"][0]["playing"]
            except Exception:
                await asyncio.sleep(1)
        return None

    @commands.command()
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def players(self, ctx):
        now = time.time()

        # Use cache if fresh
        if self.cached_players and (now - self.last_fetch < self.cache_time):
            players = self.cached_players
        else:
            players = await self.fetch_players()
            if players is None:
                return await ctx.send("❌ Unable to fetch Roblox player count. Try again in a few seconds.")

            self.cached_players = players
            self.last_fetch = now

        embed = discord.Embed(
            title="🎮 Roblox Player Count",
            description=f"**{players:,} players** currently in-game",
            color=discord.Color.green()
        )
        embed.set_footer(text="Data updates every ~15 seconds")
        await ctx.send(embed=embed)

    @players.error
    async def players_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Cooldown active! Try again in {error.retry_after:.1f}s.")

    # Close session when the cog unloads
    async def cog_unload(self):
        if self.session and not self.session.closed:
            await self.session.close()

# Required setup for Modmail plugin system
async def setup(bot):
    await bot.add_cog(Players(bot))                async with self.session.get(url, timeout=10) as res:
                    if res.status == 200:
                        data = await res.json()
                        self.universe_id = data["universeId"]
                        return self.universe_id
            except:
                await asyncio.sleep(1)
        return None

    # Fetch current player count
    async def fetch_players(self):
        universe_id = await self.get_universe_id()
        if not universe_id:
            return None

        url = f"https://games.roblox.com/v1/games?universeIds={universe_id}"
        for _ in range(3):
            try:
                async with self.session.get(url, timeout=10) as res:
                    if res.status == 200:
                        data = await res.json()
                        return data["data"][0]["playing"]
            except:
                await asyncio.sleep(1)
        return None

    @commands.command()
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def players(self, ctx):
        now = time.time()

        # Use cache if fresh
        if self.cached_players and (now - self.last_fetch < self.cache_time):
            players = self.cached_players
        else:
            players = await self.fetch_players()
            if players is None:
                return await ctx.send("❌ Roblox API error. Try again later.")

            self.cached_players = players
            self.last_fetch = now

        embed = discord.Embed(
            title="🎮 Roblox Player Count",
            description=f"**{players:,} players** currently in-game",
            color=discord.Color.green()
        )
        embed.add_field(
            name="⏳ Cooldown",
            value="You can use this command every **10 seconds**",
            inline=False
        )
        embed.set_footer(text="Data updates every ~15 seconds")

        await ctx.send(embed=embed)

    @players.error
    async def players_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ You're on cooldown! Try again in **{round(error.retry_after, 1)}s**."
            )
