import discord
import tabulate

from redbot.core import commands
from redbot.core.utils.chat_formatting import box
from typing import Any, Dict, List, Union


class ChannelShowSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, highlight_data: Dict[Union[str, int], list]):
        self._bot = bot
        self._data = highlight_data
        options, channels = [], []
        for key, _data in highlight_data.items():
            if key == "guild" and _data:
                options.append(
                    discord.SelectOption(label = "Current Guild", value = "guild")
                )
            elif channel := self._bot.get_channel(int(key)):
                options.append(
                    discord.SelectOption(label = channel.name, value = channel.id)
                )

        super().__init__(placeholder = "Select a channel !", options = options)

    async def callback(self, interaction: discord.Interaction) -> Any:
        selected_option = self.values[0]

        response = self.view.format_page(self._data[selected_option if not selected_option.isdigit() else int(selected_option)])
        await interaction.response.send_message(
            content = response
        )

class ChannelShowMenu(discord.ui.View):
    def __init__(self, bot: commands.Bot, *args, **kwargs):
        super().__init__(timeout = None)

        self.add_item(
            ChannelShowSelect(bot, *args, **kwargs)
        )

    def format_page(self, data):
        table = tabulate.tabulate(
            data, headers = 'keys', tablefmt = "pretty"
        )
        return box(table, lang = "rst")

    



