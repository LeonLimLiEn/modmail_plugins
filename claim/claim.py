from discord.ext import commands
import aiohttp
import asyncio
import time
import discord

class Players(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.place_id = 7243409883
        self.universe_id = None

        # Cache
        self.cached_players = None
        self.last_fetch = 0
        self.cache_time = 15

        self.session = aiohttp.ClientSession()

    async def get_universe_id(self):
        if self.universe_id:
            return self.universe_id

        url = f"https://apis.roblox.com/universes/v1/places/{self.place_id}/universe"

        for _ in range(3):  # retry
            try:
                async with self.session.get(url, timeout=10) as res:
                    if res.status == 200:
                        data = await res.json()
                        self.universe_id = data["universeId"]
                        return self.universe_id
            except:
                await asyncio.sleep(1)

        return None

    async def fetch_players(self):
        universe_id = await self.get_universe_id()
        if not universe_id:
            return None

        url = f"https://games.roblox.com/v1/games?universeIds={universe_id}"

        for _ in range(3):  # retry system
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

        # Use cache
        if self.cached_players and (now - self.last_fetch < self.cache_time):
            players = self.cached_players
        else:
            players = await self.fetch_players()

            if players is None:
                await ctx.send("❌ Roblox API is currently unstable. Try again in a moment.")
                return

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

    def cog_unload(self):
        asyncio.create_task(self.session.close())


async def setup(bot):
    await bot.add_cog(Players(bot))                except:
                    players = None

                # 🔁 FALLBACK METHOD (your old server loop)
                if players is None:
                    try:
                        url = f"https://games.roblox.com/v1/games/{self.place_id}/servers/Public?limit=100"
                        total_players = 0
                        cursor = None

                        while True:
                            final_url = url + (f"&cursor={cursor}" if cursor else "")

                            async with session.get(final_url, timeout=10) as res:
                                if res.status != 200:
                                    break
                                data = await res.json()

                            for server in data.get("data", []):
                                total_players += server.get("playing", 0)

                            cursor = data.get("nextPageCursor")
                            if not cursor:
                                break

                        players = total_players

                    except:
                        await ctx.send("❌ Unable to fetch player count right now.")
                        return

            # ✅ Save cache
            self.cached_players = players
            self.last_fetch = now

        # ✅ Embed UI
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

    # ✅ Cooldown message
    @players.error
    async def players_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ You're on cooldown! Try again in **{round(error.retry_after, 1)}s**.\n"
                f"(This prevents spam and keeps the bot stable)"
            )

async def setup(bot):
    await bot.add_cog(Players(bot))
