from .highlight import Highlight

async def setup(bot):
    await bot.add_cog(Highlight(bot))