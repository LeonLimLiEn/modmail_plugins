from .claim import Players

async def setup(bot):
    await bot.add_cog(Players(bot))
