import asyncio
import logging
import discord
import functools
import TagScriptEngine as tse
import re

from typing import Any, Dict, List, Literal, Optional
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
    def __init__(self, cog: commands.Cog, member: discord.Member):
        self.cog = cog
        self.member = member
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
           self._matches.append({'match': match.group(0), 'highlight': highlight['highlight'], 'type': highlight['type']})

    def remove_match(self, match: str):
        for item in self._matches:
            if item['match'] == match:
               self._matches.remove(item)

    @classmethod
    def _resolve(cls, cog, member, *args, **kwargs):
        return cls(cog, member).resolve(*args, **kwargs)

    async def resolve(self, highlights, message: discord.Message):
        member_config = self.cog.get_member_config(self.member)
        print(self.member.name, highlights)
        if not member_config['bots'] and message.author.bot:
            return self

        message_check = {
            'content': message.content,
            'clean': message.clean_content,
            'stem': ' '.join(stem(word) for word in message.content.split())
        }
        for highlight in highlights:
            highlight_text = highlight['highlight']
            pattern = {
                'default': re.compile(rf'\b{re.escape(highlight_text)}\b', re.IGNORECASE),
                'regex': re.compile(highlight_text),
                'wildcard': re.compile(''.join([f'{re.escape(char)}[ _.{re.escape(char)}-]*' for char in highlight_text]), re.IGNORECASE)
            }[highlight['type']]

            for content_type, content in message_check.items():
                if highlight['type'] == 'default':
                    result = pattern.search(content)
                else:
                    task = asyncio.get_event_loop().run_in_executor(
                        None, functools.partial(pattern.search, content)
                    )
                    try:
                        result = await asyncio.wait_for(task, timeout = 6)
                    except asyncio.TimeoutError:
                        await self.cog.send_alert(content = f'Highlight `{highlight_text}` took too long to fetch matches.\n> Belongs To : {self.member.mention}')
                        return self
                if result:
                    self.add_match(result, highlight)
                    self.matched_types.add(content_type)
                    break
        return self

    async def response_mapping(self, history: List[discord.Message], override_config = None):
        user_conf, desc = (
            override_config or self.cog.get_member_config(self.member), 
            []
        )
        content = await self.cog.tagscript_interpreter.process(
            user_conf['format']['content'], seed_variables = self.cog.get_adapters_for_message(history[-1], matches = self)
        )
        for msg in history:
            seed_variables = self.cog.get_adapters_for_message(msg, matches = self)
            resp = await self.cog.tagscript_interpreter.process(
                user_conf['format']['history'], seed_variables = seed_variables
            )
            desc.append(resp.body)

        embed = discord.Embed(
            title = self.format_title(),
            description = '\n'.join(desc),
            colour = user_conf['colour'],
            timestamp = history[0].created_at
        ).add_field(
            name = 'Source Message',
            value = f'[Jump To]({history[0].jump_url})'
        ).set_footer(text = self.format_footer() + ' | Triggered At')

        return {
            'content': content.body,
            'embed': embed
        }


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
            if not _type in ['content']: # No point showing these
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

class MatchAdapter(tse.AttributeAdapter):
    __slots__ = ("object", "_attributes", "_methods")

    def __init__(self, base):
        self.object = base
        self._attributes = {
            "count": len(self.object._matches)
        }
        self._methods = {
            "format_response": self.object.format_response
        }
    
class MessageAdapter(tse.AttributeAdapter):

    def update_attributes(self):
        additional_attributes  = {
            'content': self.object.content[:250],
            'clean_content':self.object.clean_content[:250],
        }
        self._attributes.update(additional_attributes)

class HighlightHandler:

    bot: commands.Bot
    config: Config

    def __init_sublass__(cls) -> None:
        pass

    async def get_highlights_for_message(self, message: discord.Message) -> Dict:
        highlights = {}
        
        guild_highlights, channel_highlights = (
            await self.config.guild(message.guild).all(),
            await self.config.channel(message.channel).all()
        )
        for member_id, data in guild_highlights.get('highlights', {}).items():
            highlights.setdefault(int(member_id), []).extend(data)

        for member_id, data in channel_highlights.get('highlights', {}).items():
            highlights.setdefault(int(member_id), []).extend(data)
        
        return highlights

    async def get_all_member_highlights(self, member: discord.Member):

        data = {
            member.guild.id: (await self.config.guild(member.guild).highlights()).get(str(member.id), [])
        }
        for channel_id, config in (await self.config.all_channels()).items():
            if member.guild.get_channel(channel_id):
                data[channel_id] = config.get('highlights', {}).get(str(member.id), [])

        return data

    async def process_message(self, message: discord.Message):
        pass

    async def handle_highlight_update(self, ctx: commands.Context, data, **kwargs):
        ret = await self.update_member_highlights(ctx.author, data, **kwargs)

        description, e = [], f'highlights for {kwargs.get("channel").mention}' if kwargs.get('channel') else "guild highlights"

        if data['settings']:
            description.append(
                f'Settings Applied -> {humanize_list([italics(setting) for setting in data["settings"]])}\n'
            )

        if ret['added']:
            description.append(
                f"Added {humanize_list([inline(text) for text in ret['added']])} to your {e}."
            )

        if ret['removed']:
            description.append(
                f"Removed {humanize_list([inline(text) for text in ret['removed']])} from your {e}."
            )
        
        if ret['error']:
            for reason, highlights in ret['error'].items():
                description.append(reason + ' ' + humanize_list([inline(h) for h in highlights]))

        await ctx.send('\n'.join(description))

    async def update_member_highlights(self, member: discord.Member, data: Dict[str, Any], action: Optional[str] = "add", channel = None):
        if channel:
           config_method, limit = self.config.channel(channel), 10
        else:
           config_method, limit = self.config.guild(member.guild), 25
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

            for i, highlight in enumerate(data['words']):
                hl = {
                    'highlight': highlight,
                    'type': data['type'],
                    'settings': data['settings']
                }
                if channel and len([channel_ for channel_, highlights_ in (await self.get_all_member_highlights(member)).items() if highlights_ and channel_ not in [member.guild.id, channel.id]]) >= 20:
                    ret['error'].setdefault('Limit of `20` channels exceeded, Failed to add the following -> ', []).extend(data['words'][i:])
                    break

                if action in ('add', None):
                    if len(user_config) > limit:
                        ret['error'].setdefault(f'Limit of {limit} highlights reached. Failed to add the following ->', []).extend(data['words'][i:])
                        break
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
        return ret

    async def handle_block_update(self, ctx: commands.Context, objects: List[discord.Object], action):
        current = await self.edit_member_blocks(ctx.author, objects, action)

        member_config = self.member_config.get(ctx.guild.id, {}).get(ctx.author.id, self.default_member)
        embed = discord.Embed(
            title = 'Your current ignores',
            colour = member_config['colour'],
            timestamp = ctx.message.created_at
        ).set_footer(text = f'{len(current)} ignores')

        if (user_blocks := [ctx.guild.get_member(user).mention for user in current if ctx.guild.get_member(user) != None]):
            embed.add_field(name = 'Users', value = '\n'.join(user_blocks))
            
        if (channel_blocks := [ctx.guild.get_channel(channel).mention for channel in current if ctx.guild.get_channel(channel) != None]):
            embed.add_field(name = 'Channels', value = '\n'.join(channel_blocks))
 
        await ctx.send(embed = embed)

    async def edit_member_blocks(self, member: discord.Member, objects: List[discord.Object], action: Literal['add', 'remove']):
        async with self.config.member(member).blocks() as current:
            for obj in objects:
                if not obj.id in current and action == 'add':
                   current.append(obj.id)
                elif obj.id in current and action == 'remove':
                   current.remove(obj.id)

        await self.generate_cache()
        return current

    async def create_matches(self, member: discord.Member, message: discord.Message, highlights: List[Dict[str, Any]], dummy: bool = False):
        if dummy:
            return Matches(self, member, init_matches = [{'match': match, 'highlight': match, 'type': 'default'} for match in ['Match 1', 'Match 2']])

        return await Matches._resolve(self, member, highlights = highlights, message = message)

    async def send_alert(self, *args, **kwargs):
        return await self.bot.get_channel(897450721493012500).send(*args, **kwargs)

    async def generate_cache(self):
        self.global_cache = await self.config.all()
        self.member_config = await self.config.all_members()

    def _check_cooldown(self, seconds: int):
        return min(max(seconds, self.global_cache['cooldown']['min']), self.global_cache['cooldown']['max'])

    def get_member_config(self, member: discord.Member):
        return self.member_config.get(member.guild.id, {}).get(member.id, self.default_member)

    def mark_last_seen(self, member: discord.Member, channel: discord.abc.Messageable, event_type: Literal['message', 'reaction', 'typing']):
        if not isinstance(member, discord.Member) or isinstance(channel, (discord.Thread, discord.DMChannel)): # User triggered an event
            return
        
        config = self.get_member_config(member = member)
        if not config['last_seen'].get(event_type, False):
            return
        
        self.last_seen.setdefault(channel.guild.id, {}).setdefault(member.id, {})[(channel.category or channel).id] = discord.utils.utcnow().timestamp()

    def get_adapters_for_message(self, message: discord.Message, matches: Matches, format_name: str = 'content'):
        ret = {
            'guild': tse.GuildAdapter(message.guild),
            'channel': tse.ChannelAdapter(message.channel),
            'author': tse.MemberAdapter(message.author),
            'message': MessageAdapter(message),
            'matches': MatchAdapter(Matches)
        }
        return ret
    
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