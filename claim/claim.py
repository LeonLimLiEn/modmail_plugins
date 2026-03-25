from discord.ext import commands
import aiohttp
import time
import discord

class Players(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.place_id = 7243409883

        # Cache
        self.cached_players = None
        self.last_fetch = 0
        self.cache_time = 15  # seconds

    @commands.command()
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def players(self, ctx):
        now = time.time()

        # ✅ Use cache if fresh
        if self.cached_players is not None and (now - self.last_fetch < self.cache_time):
            players = self.cached_players
        else:
            players = None

            async with aiohttp.ClientSession() as session:
                try:
                    # ✅ METHOD 1 (FAST + accurate enough)
                    url = f"https://games.roblox.com/v1/games?universeIds={self.place_id}"

                    async with session.get(url, timeout=10) as res:
                        if res.status == 200:
                            data = await res.json()
                            players = data["data"][0]["playing"]

                except:
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
