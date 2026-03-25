from discord.ext import commands
import requests

class Players(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.place_id = 7243409883  # 🔁 your game ID

    @commands.command()
    async def players(self, ctx):
        url = f"https://games.roblox.com/v1/games/{self.place_id}/servers/Public?limit=100"

        total_players = 0
        cursor = None

        try:
            while True:
                final_url = url + (f"&cursor={cursor}" if cursor else "")
                res = requests.get(final_url).json()

                for server in res["data"]:
                    total_players += server["playing"]

                cursor = res.get("nextPageCursor")
                if not cursor:
                    break

            await ctx.send(f"Players currently in-game: {total_players}")

        except Exception as e:
            await ctx.send("Error fetching player count.")
            print(e)

async def setup(bot):
    await bot.add_cog(Players(bot))
