import asyncio
import logging
import discord
import functools
import re

from copy import copy
from typing import Any, Dict, List, Optional
from redbot.core import commands, Config
from redbot.core.utils.chat_formatting import humanize_list, inline, italics
from stemming.porter2 import stem

log = logging.getLogger('red.cogs.Highlight')

def _message(message: discord.Message):
        message_raw = {
            'content': message.content,
            'clean_content': message.clean_content,
            'stem': ' '.join(stem(w) for w in message.content.split()),
            'embeds': ''
        }

        if message.embeds:
            texts = []
            for embed in message.embeds:
                for key, value in embed.to_dict().items():
                    if key in ['type', 'color']:
                        continue
                    if isinstance(value, dict):
                        for k, v in value.items():
                            if not str(v).startswith('http'): # ignore links
                                texts.append(str(v))
                    elif isinstance(value, list):
                        texts.extend(field['name'] + ' ' + field['value'] for field in value)
                    else:
                        texts.append(value)

            message_raw['embeds'] = ' '.join(texts)
        return message_raw

class Matches:
    def __init__(self):
        self._matches = []
        self.matched_types = set()

    def __len__(self):
        return self._matches.__len__()

    def __contains__(self, con: str):
        for item in self._matches:
            if item['highlight'].strip() == con.strip():
               return True
        return False

    def add_match(self, match: re.Match, highlight):
        if not any(h['highlight'] == highlight for h in self._matches):
           self._matches.append({'match': match.group(0), 'highlight': highlight.highlight, 'type': highlight.type})

    def remove_match(self, match: str):
        for item in self._matches:
            if item['match'] == match:
               self._matches.remove(item)

    @classmethod
    async def _resolve(cls, *args, **kwargs):
        return await cls().resolve(*args, **kwargs)

    async def resolve(self, highlights, message):
        message_content_data = _message(message)
        for highlight in highlights:
            result = await highlight.get_matches(message_content_data)
            if result['match']:
               self.add_match(match = result['match'], highlight = highlight)
               self.matched_types.add(result['matched_type'])
        return self

    def create_embed(self, history: List[str], message: discord.Message, settings: Dict[str, Any]):
        return discord.Embed(
            title = self.format_title(),
            description = '\n'.join(history),
            colour = settings['colour'],
            timestamp = message.created_at
        ).add_field(
            name = 'Source Message',
            value = f'[Jump To]({message.jump_url})'
        ).set_footer(text = self.format_footer() + '| Triggered At')


    def format_response(self):
        response = []
        for item in self._matches:
            conversions = {
                'default': f'\"{item["match"]}\"',
                'wildcard': f'\"{item["match" if len(item["match"]) < 100 else "[EXCEEDED 100 CHAR LIMIT]"]}\"' if item['match'].strip().lower() == item['highlight'].strip().lower() else f'\"{item["match"]}\" from wildcard `({item["highlight"]})`',
                'regex': f'\"{item["match"] if len(item["match"]) < 100 else "[EXCEEDED 100 CHAR LIMIT]"}\" from regex `({item["highlight"]})`'
            }
            response.append(conversions.get(item['type']))
        return humanize_list(response[:10])

    def format_footer(self):
        _ = []
        for _type in self.matched_types:
            if not _type in ['content']: # No point showing this
               _.append(_type)
        return ' | '.join(_)

    def format_title(self):
        matches = [item['match'].strip() for item in self._matches]

        if len(matches) < 3:
           title = ', '.join(matches)
        else:
           title = ', '.join(matches[:2]) + f' + {len(matches) - 2} more.'

        if len(title) > 50:
           title = title[:47] + '...'
        return title

class MemberHighlight:
    def __init__(self, **kwargs) -> None:
        self.highlight = kwargs.get('highlight')

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
            result = self.pattern.search(content)
            if result:
               return_data.update(match = result, matched_type = content_type)
               break
        return return_data

class HighlightHandler:

    bot: commands.Bot
    config: Config

    def __init_sublass__(cls) -> None:
        pass

    def get_highlights_for_message(self, message: discord.Message) -> Dict:
        highlights = {}
        
        guild_highlights, channel_highlights = (
            self.guild_config.get(message.guild.id, {}).copy(),
            self.channel_config.get(message.channel.id, {}).copy()
        )
        for member_id, data in guild_highlights.get('highlights', {}).items():
            highlights.setdefault(int(member_id), []).extend(data)

        for member_id, data in channel_highlights.get('highlights', {}).items():
            highlights.setdefault(int(member_id), []).extend(data)
        
        return highlights

    def get_all_member_highlights(self, member: discord.Member, as_dict = False):
        data = {
            member.guild.id: self.guild_config.get(member.guild.id, {}).get('highlights', {}).get(str(member.id), [])
        }
        data.update([(channel_id, data.get('highlights', {}).get(str(member.id), [])) for channel_id, data in self.channel_config.items() if member.guild.get_channel(channel_id)])
        if as_dict:
            for _key, _data in data.items():
                data[_key] = [highlight.to_dict() for highlight in _data]

        return data

    async def handle_highlight_update(self, ctx: commands.Context, data, **kwargs):
        ret = await self.update_member_highlights(ctx.author, data, **kwargs)

        description = []

        if ret['added']:
            description.append(
                f"+ Added {humanize_list([inline(text) for text in ret['added']])} to your highlights"
            )
            if data['settings']:
                description.append(
                    '-----------------\n'
                    f'Settings Applied -> {humanize_list([italics(setting) for setting in data["settings"]])}'
                )

        if ret['removed']:
            description.append(
                f"- Removed {humanize_list([inline(text) for text in ret['added']])} from your highlights"
            )
        
        if ret['error']:
            for reason, highlights in ret['error'].items():
                description.append(reason + ' ' + humanize_list([inline(h) for h in highlights]))

        await ctx.send('\n'.join(description))

    async def update_member_highlights(self, member: discord.Member, data: Dict[str, Any], action: Optional[str] = "add", channel = None):
        if channel:
           config_method = self.config.channel(channel)
        else:
           config_method = self.config.guild(member.guild)
        ret = dict(added = [], removed = [], error = {})

        # {'words': ['hm', 'aaaa'], 'multiple': True, 'regex': False, 'wildcard': False, 'settings': [], 'type': 'default'}
        async with config_method.highlights() as config:
            user_config: List[str, Any] = config.setdefault(str(member.id), [])

            for word in data['words'].copy():
                if any(_highlight['highlight'] == word for _highlight in user_config) and action == "add":
                    ret['error'].setdefault('The following words were already highlighted for you ->', []).append(word)
                    data['words'].remove(word)

                if not any(_highlight['highlight'] == word for _highlight in user_config) and action == "remove":
                    ret['error'].setdefault('The following words were not highlighted for you ->', []).append(word)
                    data['words'].remove(word)

            for highlight in data['words']:
                hl = {
                    'highlight': highlight,
                    'type': data['type'],
                    'settings': data['settings']
                }
                if action in ('add', None):
                    if not any(_highlight['highlight'] == highlight for _highlight in user_config):
                        user_config.append(hl)
                        ret['added'].append(hl['highlight'])
                        continue

                if action in ('remove', None):
                    if to_remove := [_highlight for _highlight in user_config if _highlight['highlight'] == highlight]:
                        for _data in to_remove:
                            user_config.remove(_data)
                            ret['removed'].append(_data['highlight'])                    
                        continue
                    
        await self.generate_cache()
        return ret

    async def generate_cache(self):
        await self.bot.wait_until_ready()
        self.guild_config = await self.config.all_guilds()
        self.channel_config = await self.config.all_channels()
        self.member_config = await self.config.all_members()
        self.global_cache = await self.config.all()

        self._handle_cache()

    def _handle_cache(self):
        for guild_id, data in self.guild_config.items():
            for member_id, highlights in data.get('highlights', {}).items():
                data['highlights'][member_id] = [MemberHighlight(**highlight) for highlight in highlights]

        for channel_id, data in self.channel_config.items():
            for member_id, synced_channel_id in data.get('synced_with', {}).items():
                if synced_channel_id:
                   self.channel_config[channel_id]['highlights'][member_id] = self.channel_config.get(synced_channel_id, {}).get('highlights', {}).get(member_id, [])

        for channel_id, data in self.channel_config.items():
            for member_id, highlights in data.get('highlights', {}).items():
                data['highlights'][member_id] = [MemberHighlight(**highlight) for highlight in highlights]

    def _check_cooldown(self, seconds: int):
        return min(max(seconds, self.global_cache['cooldown']['min']), self.global_cache['cooldown']['max'])
    
class HighlightView(discord.ui.View):
   def __init__(self, message: discord.Message, highlights: list):
       super().__init__(timeout = None)
       self.message = message
       self.content = message.content
       self.attachments = message.attachments
       self.embeds = message.embeds
       self.highlights = highlights
       self.data = {}

       if len(self.content) > 500 or self.attachments or self.embeds:

          button = discord.ui.Button(
             label = 'View Message',
             style = discord.ButtonStyle.secondary
          )
          button.callback = self.execute
          self.add_item(button)

       else:
          button = discord.ui.Button(
             label = 'Jump To Source',
             style = discord.ButtonStyle.link,
             url = self.message.jump_url
          )
          self.add_item(button)

   async def execute(self, interaction: discord.Interaction):
       
       for highlight in self.highlights:
           regex = re.compile(rf'\b{re.escape(highlight)}\b', flags = re.IGNORECASE)
           replace_re = r'**__\g<0>__**'
           content = regex.sub(replace_re, self.content)

           for embed in self.embeds:
               embed.description = regex.sub(replace_re, embed.description)[:2000] if embed.description else None
               fields = []
               for field in embed.fields:
                   value = field.value = regex.sub(replace_re, field.value) if field.value else None
                   fields.append({'name': field.name, 'value': value})
               embed.clear_fields()
               [embed.add_field(**field) for field in fields]
            
       data = {
             'content': content,
             'embeds': self.embeds,
             'files': [await attach.to_file() for attach in self.attachments],
             'view': discord.ui.View.from_message(self.message),
             'ephemeral': True
       }

       await interaction.response.send_message(**data)

       self.clear_items()
       button = discord.ui.Button(
            label = 'Jump To Source',
            style = discord.ButtonStyle.link,
            url = self.message.jump_url
       )
       self.add_item(button)
       await interaction.message.edit(view = self)