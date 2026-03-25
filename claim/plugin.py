from .claim import Players  # import your claim.py class

async def setup(bot):
    await bot.add_cog(Players(bot))
