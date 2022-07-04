TRADES_GUILD_ID: int = 719180744311701505

from .trades import Trades

async def setup(bot):
    await bot.add_cog(Trades(bot = bot))