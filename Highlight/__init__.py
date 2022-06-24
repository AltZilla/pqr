from .highlight import Highlight

async def setup(bot):
    cog = Highlight(bot)
    await bot.add_cog(cog)