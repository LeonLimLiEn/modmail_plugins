from discord.ext import commands
import aiohttp
import asyncio
import time
import discord

class Players(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.place_id = 132702823704482  # Your Roblox place ID

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

        for _ in range(3):  # retry 3 times
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

        for _ in range(3):  # retry 3 times
            try:
                async with self.session.get(url, timeout=10) as res:
                    if res.status == 200:
                        data = await res.json()
                        return data["data"][0]["playing"]
            except Exception:
                await asyncio.sleep(1)

        # Fallback: sum all public servers
        url_servers = f"https://games.roblox.com/v1/games/{self.place_id}/servers/Public?limit=100"
        total_players = 0
        cursor = None

        try:
            while True:
                final_url = url_servers + (f"&cursor={cursor}" if cursor else "")
                async with self.session.get(final_url, timeout=10) as res:
                    if res.status != 200:
                        break
                    data = await res.json()

                for server in data.get("data", []):
                    total_players += server.get("playing", 0)

                cursor = data.get("nextPageCursor")
                if not cursor:
                    break

            return total_players
        except Exception:
            return None

    @commands.command()
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def players(self, ctx):
        now = time.time()

        # Use cache if fresh
        if self.cached_players is not None and (now - self.last_fetch < self.cache_time):
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
            await ctx.send(f"⏳ Cooldown active! Try again in {error.retry_after:.1f}s.")

    # Properly close session when the Cog unloads
    async def cog_unload(self):
        if self.session and not self.session.closed:
            await self.session.close()

# Setup for Modmail plugin
async def setup(bot):
    await bot.add_cog(Players(bot))
