from .players import Players

async def setup(bot):
    await bot.add_cog(Players(bot))
