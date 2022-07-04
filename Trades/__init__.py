from .trades import Trades

async def setup(bot):
    await bot.add_cog(Trades(bot = bot))