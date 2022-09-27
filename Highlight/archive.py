"""All stuff worked on and might be used later on :thumbsup:"""

import discord
import asyncio
import functools
import tabulate
import re

from fuzzywuzzy import process
from redbot.core import commands
from redbot.core.utils.chat_formatting import underline, box

from typing import Any, Dict, List

class MemberHighlight:
    def __init__(self, cog: commands.Cog, **kwargs) -> None:
        self.cog = cog
        self.highlights = kwargs.get('highlights')
        self.bots = kwargs.get('bots', False)
        self.embeds = kwargs.get('embeds', False)
        self.cooldown = cog._check_cooldown(kwargs.get('cooldown', 30))
        self.colour = kwargs.get('colour')

        if not self.highlight:
           raise TypeError('The Highlight kwargs is required..')

        self.type = kwargs.get('type', 'default')
        self.settings = kwargs.get('settings', [])

        type_converter = {
            'default': re.compile(rf'\b{re.escape(self.highlight)}\b', re.IGNORECASE),
            'regex': re.compile(self.highlight),
            'wildcard': re.compile(''.join([f'{re.escape(char)}[ _.{re.escape(char)}-]*' for char in self.highlight]), re.IGNORECASE)
        }
        self.pattern = type_converter.get(self.type)

    def __repr__(self) -> str:
        return self.highlight
            
    def to_dict(self):
        return {
            'Highlight': self.highlight,
            'Type': self.type,
            'Settings': self.settings
        }

    def filter_contents(self, data: Dict[str, str], force: Dict[str, bool] = {}):
        return data

    async def get_matches(self, content_dict: Dict[str, str]):
        return_data = {'match': None, 'matched_type': None}
        for content_type, content in content_dict.items():
            process = self.cog.re_pool.apply_async(self.pattern.findall, (content,))
            task = asyncio.get_event_loop().run_in_executor(
                None, functools.partial(process.get, timeout = 2)
            )
            result = await asyncio.wait_for(task, timeout = 5)
            if result:
               return_data.update(match = result, matched_type = content_type)
               break
        return return_data

class MemberconfigCache:
    def __init__(self, guild_highlights: Dict[str, Any], channel_highlights: Dict[str, Any], config: Dict[str, Any]):
        self.guild_highlights = guild_highlights.values()
        self.channel_highlights = channel_highlights.values()
        self._raw = config

    @property
    def blocks(self):
        return self._raw.get('blocks', [])

    @property
    def bots(self):
        return self._raw.get('bots', False)

    @property
    def embeds(self):
        return self._raw.get('embeds', False)

    @property
    def colour(self):
        return self._raw.get('colour', discord.Colour.green())

    async def match(self, cog: commands.Cog, message: discord.Message):
        message_check = {
            'content': message.content
        }
        return_data = {'matches': [], 'matched_types': []}
        for highlight in self.guild_highlights:
            pattern = {
                'default': re.compile(rf'\b{re.escape(self.highlight)}\b', re.IGNORECASE),
                'regex': re.compile(self.highlight),
                'wildcard': re.compile(''.join([f'{re.escape(char)}[ _.{re.escape(char)}-]*' for char in self.highlight]), re.IGNORECASE)
            }[highlight['type']]

            for content_type, content in message_check.items():
                process = cog.re_pool.apply_async(pattern.findall, (content,))
                task = asyncio.get_event_loop().run_in_executor(
                    None, functools.partial(process.get, timeout = 2)
                )
                result = await asyncio.wait_for(task, timeout = 5)
                if result:
                    return_data['match'].append(result)
                    return_data['matched_type'].append(content_type)
                    break
        return return_data

class GuildConfigCache:
    def __init__(self, guild: discord.Guild):
        self._guild = guild
        self.cache: Dict[int, List[dict]] = {}

    async def init_cache(self, cog: commands.Cog):
        guild_highlights = await cog.config.guild(self._guild).all()
        all_channels = await cog.config.all_channels()
        all_members: Dict[int, dict] = await cog.config.all_members(guild = self._guild)

        for member_id, config in all_members.items():
            self.cache[member_id] = MemberconfigCache()

# converters .......

class FuzzyChannels(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str):
        try:
            return await commands.GuildChannelConverter().convert(ctx, argument)
        except Exception:
            channel, acc = process.extractOne(argument, [channel.name for channel in ctx.guild.channels])
            if acc < 60:
                raise commands.ChannelNotFound(argument)
            channel = discord.utils.get(ctx.guild.channels, name = channel)
            if not (isinstance(channel, discord.TextChannel) or isinstance(channel, discord.VoiceChannel)):
               raise commands.BadArgument('The channel should be a Text channel or Voice channel.')
            return channel

class TimeConverter(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str):
       matches = re.findall(r'([0-9]+) *([a-zA-Z]+)', argument)
       seconds = 0
       for match in matches:
           if match[1].startswith("s"):
              seconds  += int(match[0])
           elif match[1].startswith("m"):
              seconds  += (int(match[0]) * 60)
           elif match[1].startswith("h"):
              seconds  += (int(match[0]) * 3600)
           elif match[1].startswith("d"):
              seconds  += (int(match[0]) * 86400)
           elif match[1].startswith("w"):
              seconds  += (int(match[0]) * 604800)
           elif match[1].startswith("y"):
              seconds  += (int(match[0]) * 31536000)
           else:
              seconds += int(match[0])
       return seconds


# ------------- menus ---------------

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