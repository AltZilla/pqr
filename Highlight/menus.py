import discord
import tabulate

from redbot.core import commands
from redbot.core.utils.chat_formatting import box, underline
from typing import Any, Dict, List, Union


class ChannelShowSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, highlight_data: Dict[Union[str, int], list]):
        self._bot = bot
        self._data = highlight_data
        self._objects = {}
        for _id, _data in filter(lambda d: d[1], self._data.items()):
            if guild := self._bot.get_guild(_id):
                self._objects[_id] = guild
            elif channel := self._bot.get_channel(_id):
                self._objects[_id] = channel
        
        options = [discord.SelectOption(label = obj[1].name, value = obj[1].id) for obj in sorted(self._objects.items(), key = lambda k: getattr(k[1], 'position', 0))]
        super().__init__(placeholder = "Select a channel...", options = options)

    async def callback(self, interaction: discord.Interaction) -> Any:
        selected_option = self.values[0]

        table = tabulate.tabulate(
            self._data[int(selected_option)], headers = 'keys', tablefmt = "pretty"
        )
        embed = discord.Embed(
            title = f"Current highlights for {interaction.user.name} in {underline(self._objects[int(selected_option)].name)}",
            description = box(table, lang = "prolog")
        )
        await interaction.response.defer()
        await interaction.message.edit(
            content = None,
            embed = embed
        )

class ChannelShowMenu(discord.ui.View):
    def __init__(self, bot: commands.Bot, *args, **kwargs):
        super().__init__(timeout = None)

        self.add_item(
            ChannelShowSelect(bot, *args, **kwargs)
        )

    



