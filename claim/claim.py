from discord.ext import commands
import aiohttp
import time
import discord

class Players(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.place_id = 7243409883

        # Cache system
        self.cached_players = None
        self.last_fetch = 0
        self.cache_time = 15  # seconds

    @commands.command()
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def players(self, ctx):
        now = time.time()

        # ✅ Use cache if still fresh
        if self.cached_players is not None and (now - self.last_fetch < self.cache_time):
            players = self.cached_players
        else:
            url = f"https://games.roblox.com/v1/games/{self.place_id}/servers/Public?limit=100"
            total_players = 0
            cursor = None

            async with aiohttp.ClientSession() as session:
                try:
                    while True:
                        final_url = url + (f"&cursor={cursor}" if cursor else "")

                        async with session.get(final_url, timeout=10) as res:
                            if res.status != 200:
                                await ctx.send("⚠️ Roblox API error. Try again later.")
                                return

                            data = await res.json()

                        for server in data.get("data", []):
                            total_players += server.get("playing", 0)

                        cursor = data.get("nextPageCursor")
                        if not cursor:
                            break

                except Exception as e:
                    await ctx.send("❌ Error fetching player count.")
                    print("DEBUG:", e)
                    return

            # ✅ Save cache
            self.cached_players = total_players
            self.last_fetch = now
            players = total_players

        # ✅ Embed UI
        embed = discord.Embed(
            title="🎮 Roblox Player Count",
            description=f"**{players} players** currently in-game",
            color=discord.Color.green()
        )

        embed.set_footer(text="Updates every 15 seconds")

        await ctx.send(embed=embed)

    # ✅ Cooldown message
    @players.error
    async def players_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Slow down! Try again in {round(error.retry_after, 1)}s")

async def setup(bot):
    await bot.add_cog(Players(bot))
