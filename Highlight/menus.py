import discord
import tabulate

from redbot.core import commands
from redbot.core.utils.chat_formatting import box, underline
from typing import Any, Dict, List, Union


class ChannelShowSelect(discord.ui.Select):
    def __init__(self, options: List[discord.SelectOption]):
        super().__init__(
            placeholder = "Select a page...", 
            options = options
        )

    async def callback(self, interaction: discord.Interaction) -> Any:
        selected_option = self.values[0]
        embed = self.view.handle_request(selected_option)

        await interaction.response.defer()
        await interaction.message.edit(
            embed = embed
        )

class ChannelShowMenu(discord.ui.View):
    def __init__(self, ctx: commands.Context, highlight_data, blocks):
        self._ctx = ctx
        self._data = highlight_data
        self._blocks = blocks
        self._objects = {}
        for _id, _data in filter(lambda d: d[1], self._data.items()):
            if guild := self._ctx.bot.get_guild(_id):
                self._objects[_id] = guild
            elif channel := self._ctx.bot.get_channel(_id):
                self._objects[_id] = channel

        super().__init__(timeout = None)
        self.add_item(ChannelShowSelect(options = [discord.SelectOption(label = obj[1].name, value = obj[1].id) for obj in sorted(self._objects.items(), key = lambda k: getattr(k[1], 'position', 0))]))

    def handle_request(self, selected_option) -> discord.Embed:

        table = tabulate.tabulate(
            self._data[int(selected_option)], headers = 'keys', tablefmt = 'pretty'
        )
        obj = self._objects[int(selected_option)]
        embed = discord.Embed(
            title = f"Your current highlights in {underline(obj.name)}"[:50],
            description = box(table, lang = "prolog"),
            colour = self._ctx.cog.member_config.get(self._ctx.guild.id, {}).get(self._ctx.author.id, {}).get('colour', discord.Colour.green())
        )

        if isinstance(obj, discord.Guild):
            if (user_blocks := [self._ctx.guild.get_member(user).mention for user in self._blocks if self._ctx.guild.get_member(user) != None]):
                embed.add_field(name = 'Ignored Users', value = '\n'.join(user_blocks), inline = False)
            
            if (channel_blocks := [self._ctx.guild.get_channel(channel).mention for channel in self._blocks if self._ctx.guild.get_channel(channel) != None]):
                embed.add_field(name = 'Ignored Channels', value = '\n'.join(channel_blocks), inline = False)

        return embed

    async def send(self, start_value = None):
        embed = self.handle_request(start_value or self._ctx.guild.id)
        await self._ctx.send(
            embed = embed,
            view = self
        )

    



