import contextlib
import discord
import asyncio
import time
import logging
import datetime
import yaml
import unicodedata
import re

from io import BytesIO
from copy import copy
from redbot.core import commands, Config
from redbot.core.utils.chat_formatting import humanize_list
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.predicates import ReactionPredicate
from .Helpers import Queue, HighlightView, TimeConverter, OCRSpace
from .converters import HighlightFlagResolver
from stemming.porter2 import stem
from typing import Union, List, Optional, Dict
from humanfriendly import format_timespan


log = logging.getLogger('red.cogs.Highlight')

def default_check():

   async def predicate(ctx: commands.Context):
      if ctx.author.guild_permissions.manage_guild:
         return True
      allowed_roles = await ctx.cog.config.guild(ctx.guild).allowed_roles()
      if any(role.id in allowed_roles for role in ctx.author.roles) or allowed_roles == []:
         return True
      return False
   return commands.check(predicate)

class Highlight(commands.Cog):

      __version__ = "1.0.0"
      __author__ = "AltZilla"


      def __init__(self, bot: commands.Bot):
          self.bot = bot
          self.config = Config.get_conf(self, identifier = 1698497658475)
          self.config.register_guild(
            highlights = {},
            allowed_roles = []
          )
          self.config.register_channel(
            highlights = {}
          )
          self.config.register_member(
            blocks = [],
            cooldown = 60,
            onlyoffline = False,
            bots = False,
            images = False,
            colour = discord.Colour.green().value
          )
          self.queue = Queue(maxsize = 0)
          self.ocr = OCRSpace()
          self.ocr_count = 0
          self.last_seen = {}
          self.cooldowns = {}

      def format_help_for_context(self, ctx: commands.Context):
          pre_processed = super().format_help_for_context(ctx)
          return f"{pre_processed}\nCog Version: {self.__version__}\nAuthor: {self.__author__}"

      async def get_matches(self, highlight_data: List[dict], *, message_data: dict, config: dict) -> List[str]:
          matches = []
          string = message_data['content']
          if config['bots']:
             string += ' ' + message_data.get('bot_content', '')

          if config['images']:
             string += ' ' + message_data.get('attach_content', '')

          async def resolve(data: dict):
              s = copy(string)
              setting = data['setting']
              if (not config['bots']) and (setting == 'bots') and (message_data['message'].author.bot):
                 s += ' ' + message_data.get('bot_content', '')
              if (not config['images']) and (setting == 'images'):
                 s += ' ' + message_data.get('attach_content', '')
              stemmed_string = ' '.join(stem(word) for word in s.split()).lower()
              type = data['type']
              if type == 'default':
                 pattern = re.compile(rf'\b{re.escape(data["highlight"])}\b', re.IGNORECASE)
              elif type == 'regex':
                 pattern = re.compile(data['highlight'], re.IGNORECASE)
              elif type == 'wildcard':
                 word = '[_\-. ]{0,3}'.join([re.escape(char) for char in data['highlight']])
                 pattern = re.compile(r'\b[a-zA-Z0-9_\-.]{0,3}' + word + r'[a-zA-Z0-9_\-.]{0,3}\b', re.IGNORECASE) 
                 stemmed_string = unicodedata.normalize('NFKD', stemmed_string)
              if pattern.findall(string):
                  matches.append(data['highlight'])
              elif pattern.findall(stemmed_string):
                  matches.append(data['highlight'])
            
          await asyncio.gather(
            *[resolve(data) for data in highlight_data]
          )

          return matches

      async def get_message_data(self, message: discord.Message):
         message_data = {
            'message': message,
            'content': message.content if not message.author.bot else ''
         }

         if message.embeds:
            texts = []
            for embed in message.embeds:
                if (title := embed.title):
                   texts.append(title)
                if (description := embed.description):
                   texts.append(description)
                for field in embed.fields:
                   if (name := field.name):
                      texts.append(name)
                   if (value := field.value):
                      texts.append(value)
                if (footer := embed.footer.text):
                   texts.append(footer)
                if (author := embed.author.name):
                   texts.append(author)
            message_data['bot_content'] = ' '.join(texts) + (message.content if message.author.bot else '')


         if message.attachments and not message.author.bot:
            texts = []
            for attach in message.attachments:
                try:
                     texts.append(await self.ocr.ocr_url(attach.url))
                     self.ocr_count += 1
                except Exception:
                     continue
            message_data['attach_content'] = ' '.join(texts)
         
         return message_data
               
      @commands.Cog.listener('on_message')
      async def on_message(self, message: discord.Message):

         if not message.guild or isinstance(message.channel, discord.DMChannel):
            return

         if await self.bot.cog_disabled_in_guild(self, message.guild):
            return

         self.last_seen.setdefault(message.guild.id, {}).setdefault(message.author.id, {})[(message.channel.category or message.channel).id] = time.time()

         guild_highlights, channel_highlights = (
            await self.config.guild(message.guild).highlights(),
            await self.config.channel(message.channel).highlights()
         )
         guild_highlights.update(channel_highlights)

         message_data = await asyncio.create_task(self.get_message_data(message))

         for member, highlight in (guild_highlights.items()):
             if not (member := message.guild.get_member(int(member))):
                continue

             data = await self.config.member(member).all()
             matches = await self.get_matches(highlight_data = highlight, message_data = message_data, config = data)
             if not matches:
                continue
             if message.channel.permissions_for(member).read_messages != True:
                continue
             if any(x.id in data['blocks'] for x in [message.author, message.channel]):
                continue
             if data['onlyoffline'] and not member.status == discord.Status.offline:
                continue 
             if last_seen := self.last_seen.get(message.guild.id, {}).get(member.id):
                filtered = list(filter(lambda t: t > (time.time() - 300), last_seen.values()))
                if ((x := last_seen.get((message.channel.category or message.channel).id)) and x > (time.time() - 300)) or len(filtered) > 2:
                   continue
             if (cd := self.cooldowns.get(message.guild.id, {}).get(member.id)) and cd >= (time.time() - data['cooldown']):
                continue
             self.cooldowns.setdefault(message.guild.id, {})[member.id] = time.time()

             history = [
               '**[<t:{timestamp}:T>] {message.author}:** {message.content} {attachments} {embeds}'.format(
                  timestamp = int(message.created_at.timestamp()),
                  message = message,
                  attachments = f' <Attachments {", ".join([f"[{index}({attach.url})]" for index, attach in enumerate(message.attachments)])}>' if message.attachments else '',
                  embeds = ' [embeds]' if message.embeds else ''
               )
             ]
             with contextlib.suppress(discord.NotFound): # This is done to prevent errors if the channel got deleted.
                async for msg in message.channel.history(limit = 4, before = message.created_at):
                     history.insert(0, f'[<t:{int(msg.created_at.timestamp())}:T>] **{msg.author}:** {msg.content[:200]}')

             formated = humanize_list([f'\"{x}\"' for x in matches])
             if (len(title := ', '.join(matches) if len(matches) < 3 else ', '.join(matches[:2]) + f' + {len(matches) - 2} more.') > 50):
                title = title[:47] + '...'
             
             embed = discord.Embed(
                title = title,
                description = '\n'.join(history),
                timestamp = message.created_at,
                colour = data['colour']
             ).add_field(
                name = 'Source Message',
                value = f'[Jump To]({message.jump_url})'
             ).set_footer(
                text = 'Triggered At'
             )

             await self.queue.put(
                (
                   member, {
                      'content': f'In **{message.guild.name}** {message.channel.mention}, you were mentioned with the highlighted word{"s" if len(matches) > 1 else ""} {formated}.',
                      'embed': embed,
                      'view': HighlightView(message, [d['highlight'] for d in highlight])
                   }
                )
             )

      @commands.Cog.listener('on_user_activity')
      async def on_user_activity(self, user: Union[discord.Member, discord.User], channel: discord.abc.Messageable):
         if not isinstance(channel, discord.DMChannel):
            self.last_seen.setdefault(channel.guild.id, {}).setdefault(user.id, {}).setdefault((channel.category or channel).id, time.time())

      @commands.Cog.listener('on_typing')
      async def on_typing(self, channel, user, when):
         self.bot.dispatch('user_activity', user, channel)

      @commands.Cog.listener('on_reaction_add')
      @commands.Cog.listener('on_reaction_remove')
      async def on_reaction(self, reaction, user):
         self.bot.dispatch('user_activity', user, reaction.message.channel)

      @commands.group(name = 'highlight', aliases = ['hl'], invoke_without_command = True)
      @commands.check(default_check())
      @commands.cooldown(1, 5, commands.BucketType.user)
      async def highlight(self, ctx: commands.Context, *, word: HighlightFlagResolver):
         """Base command for highlights.

         You will not get Highlighted in a Category or Channel you have recently been 'seen' in within 5 minutes, you can get 'seen' in a channel/category by either-
            - Adding / Removing a reaction.
            - Trigger Typing.
            - Sending a message.

         If you were last seen in more than 2 categories, you will not get highlighted for the entire guild.
         """
         await ctx.invoke(self.bot.get_command('highlight add'), word = word)
      
      @highlight.command(name = 'add', aliases = ['+'])
      async def highlight_add(self, ctx: commands.Context, *, word: HighlightFlagResolver):
         """Add words to your highlights.

         You can add a maximum of 25 highlights per guild, and 10 per channel.

         **Flags:**
           `--multiple`: Add multiple words to your highlights at once.
           `--channel`: Add the word(s) to a specified channel's highlights, if the flag is used and no channel is specified, the channel where the command is ran is used.
           `--wildcard`: Tries to search for bypasses by either underscores, dots and or special characters while fetching matches.
           `--regex`: Add a Regular expression to your highlights. It is suggested you [learn regex](https://github.com/ziishaned/learn-regex) and [debug](https://regex101.com/) it first.
           `--bots`: Recieve highlights from bots. This also highlights you for embeds.
           `--images`: Recieve highlights from text in images, images sent by bots are ignored even if you have bot highlights enabled.
         
         """

         if any(len(x) > 50 for x in word['words']):
            return await ctx.send('The word cannot be more than 50 characters long.')
      
         if any(len(x) < 2 for x in word['words']):
            return await ctx.send('The word must be atleast 2 characters long.')

         channel = word['channel']

         config_method = self.config.channel(channel).highlights() if channel else self.config.guild(ctx.guild).highlights()
     
         async with config_method as config:
               user_config  = config.setdefault(str(ctx.author.id), [])
               
               for d in user_config:
                   if d['highlight'] in word['words']:
                      return await ctx.send('\"{highlight}\" is already in your {extra}.'.format(
                           highlight = d['highlight'],
                           extra = f'highlights for {channel}' if channel else 'guild highlights'
                      ))

               if len(config) + len(word['words']) >= (limit := 10 if channel else 25):
                  return await ctx.reply('You have reached the maximum of `{limit}` highlights for this {type}.'.format(
                     limit = limit,
                     type = 'channel' if channel else 'guild'
                  ))
   
               data = [
                  {
                     'highlight': highlight, 
                     'channel': channel.id if channel else None, 
                     'type': word['type'],
                     'setting': word['setting']
                  }
                    for highlight in word['words']
               ]
               user_config.extend(data)
               config[str(ctx.author.id)] = user_config

         await ctx.reply('Added {formatted} to your {extra}.'.format(
            formatted = humanize_list([f"\'{x}\'" for x in word['words']]),
            extra = f'highlights for {channel.mention}' if channel else 'guild highlights'
         ))
      
      @highlight.command(name = 'remove', aliases = ['-'])
      async def highlight_remove(self, ctx: commands.Context, *, word: HighlightFlagResolver):
         """Removes a word from your highlights."""
      
         channel = word['channel']
         config_method = self.config.channel(channel).highlights() if channel else self.config.guild(ctx.guild).highlights()

         async with config_method as config:
            user_config = config.get(str(ctx.author.id), [])
            if not user_config:
               return await ctx.send('You have no highlights added.')
            
            not_highlighted = [w for w in word['words'] if not any(d['highlight'] == w for d in user_config)]
            if not_highlighted:
               return await ctx.send('{formatted} is not highlighted for you.'.format(
                  formatted = humanize_list([f"\'{x}\'" for x in not_highlighted])
               ))

            for d in user_config:
               if d['highlight'] in word['words']:
                  user_config.remove(d)
            config[str(ctx.author.id)] = user_config
            
         return await ctx.reply('Removed {formatted} from your {extra}.'.format(
            formatted = humanize_list([f"\'{x}\'" for x in word['words']]),
            extra = f'Highlights for {channel.mention}' if channel else 'guild highlights'
         ))

      @highlight.command(name = 'ignore', aliases = ['block'])
      async def highlight_ignore(self, ctx: commands.Context, blocks: commands.Greedy[Union[discord.Member, discord.TextChannel, discord.VoiceChannel]]):
         """Blocks a Member or Channel from Highlighting you."""

         async with self.config.member(ctx.author).blocks() as current:
            current = list(set(current + [obj.id for obj in blocks]))
            await self.config.member(ctx.author).blocks.set(current)

         member_config = await self.config.member(ctx.author).all()
         embed = discord.Embed(
            title = 'Your current ignores',
            colour = member_config['colour'],
            timestamp = datetime.datetime.utcnow()
         ).set_footer(text = f'{len(current)} ignores')

         if (user_blocks := [ctx.guild.get_member(user).mention for user in current if ctx.guild.get_member(user) != None]):
            embed.add_field(name = 'Users', value = '\n'.join(user_blocks), inline = False)
            
         if (channel_blocks := [ctx.guild.get_channel(channel).mention for channel in current if ctx.guild.get_channel(channel) != None]):
            embed.add_field(name = 'Channels', value = '\n'.join(channel_blocks), inline = False)

         return await ctx.reply(embed = embed)

      @highlight.command(name = 'unignore', aliases = ['unblock'])
      async def highlight_unignore(self, ctx: commands.Context, blocks: commands.Greedy[Union[discord.Member, discord.TextChannel, discord.VoiceChannel]]):
         """Unblocks a Member or Channel from Highlighting you."""

         async with self.config.member(ctx.author).blocks() as current:
            for obj in blocks:
               if obj.id in current:
                  current.remove(obj.id)

         member_config = await self.config.member(ctx.author).all()
         embed = discord.Embed(
            title = 'Your current ignores',
            colour = member_config['colour'],
            timestamp = datetime.datetime.utcnow()
         ).set_footer(text = f'{len(current)} ignores')

         if (user_blocks := [ctx.guild.get_member(user).mention for user in current if ctx.guild.get_member(user) != None]):
            embed.add_field(name = 'Users', value = '\n'.join(user_blocks))
            
         if (channel_blocks := [ctx.guild.get_channel(channel).mention for channel in current if ctx.guild.get_channel(channel) != None]):
            embed.add_field(name = 'Channels', value = '\n'.join(channel_blocks))

         return await ctx.reply(embed = embed)

      @highlight.command(name = 'show', aliases = ['list', 'display'])
      async def highlight_show(self, ctx: commands.Context, channel: Optional[Union[discord.TextChannel, discord.VoiceChannel]], show_all: Optional[bool]):
         """Shows your current highlights."""

         member_config = await self.config.member(ctx.author).all()
         if show_all:
            yml_data = {'GUILD': {}}
            guild = (await self.config.guild(ctx.guild).highlights()).get(str(ctx.author.id), [])
            for highlight in guild:
                yml_data['GUILD'][highlight['highlight']] = {
                    'setting': highlight['setting'],
                    'type': highlight['type']
                }
            channels = await self.config.all_channels()
            for channel_id, data in channels.items():
                if not (data := data.get('highlights', {}).get(str(ctx.author.id))):
                   continue
                channel = ctx.guild.get_channel(channel_id)
                if channel:
                   yml_data[channel.id] = [
                       {highlight['highlight']: {'setting': highlight['setting'], 'type': highlight['type']}}
                       for highlight in data
                   ]
            fp = BytesIO(yaml.dump(yml_data).encode('utf-8'))
            await ctx.author.send(file = discord.File(fp, 'highlights.yaml'))
            return await ctx.send('I\'ve sent you a file via DM.')
         if channel:
            current = (await self.config.channel(channel).highlights()).get(str(ctx.author.id), [])
            if not current:
               return await ctx.reply('You are not currently tracking anything.')  

            embed = discord.Embed(
               title = f'Your current highlights for #{channel.name}',
               description = '\n'.join(c['highlight'] for c in current),
               timestamp = datetime.datetime.utcnow(),
               colour = member_config.get('colour', 0x00ff00)
            )    
            return await ctx.reply(embed = embed)
         current = (await self.config.guild(ctx.guild).highlights()).get(str(ctx.author.id), [])
         if not current:
            return await ctx.reply('You are not currently tracking anything.')

         embed = discord.Embed(
               title = 'You\'re currently tracking the following words',
               description = '\n'.join(c['highlight'] for c in current),
               timestamp = datetime.datetime.utcnow(),
               colour = member_config.get('colour', 0x00ff00)
         )
 
         if (user_blocks := [ctx.guild.get_member(user).mention for user in member_config['blocks'] if ctx.guild.get_member(user) != None]):
            embed.add_field(name = 'Ignored Users', value = '\n'.join(user_blocks))

         if (channel_blocks := [ctx.guild.get_channel(channel).mention for channel in member_config['blocks'] if ctx.guild.get_channel(channel) != None]):
            embed.add_field(name = 'Ignored Channels', value = '\n'.join(channel_blocks))

         return await ctx.reply(embed = embed)

      @highlight.command(name = 'sync')
      async def highlight_sync(self, ctx: commands.Context, base_channel: Union[discord.TextChannel, discord.VoiceChannel], channels_and_categories: commands.Greedy[Union[discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel]]):
         """Syncs your highlights from one channel to multiple others.
         
         This will replace the highlights of all the channels mentioned in `<channels_and_categories>` with those of the base channel.
         
         **Arguments:**
          - `<base_channel>`: The channel to sync highlights from.
          - `<channels_and_categories>`: The channels to sync highlights to, if a category is passed, highlights are synced with all the channels in that category. Including voice channels.
          
         """
         channels = [channel for channel in channels_and_categories if not isinstance(channel, discord.CategoryChannel)]
         for channel in channels_and_categories:
             if isinstance(channel, discord.CategoryChannel):
               channels.extend(c for c in channel.channels)
         
         base_config = (await self.config.channel(base_channel).highlights()).get(str(ctx.author.id), [])
         if not base_config:
            return await ctx.send(f'You have no highlights for {base_channel.mention}.')

         msg = await ctx.send(f'Are you sure you want to sync **{len(base_config)}** highlight{"s" if len(base_config) > 1 else ""} from {base_channel.mention} to **{len(channels)}** other channel{"s" if len(channels) > 1 else ""}?\n\n**Note:** This will **replace** the highlights of all the channels passed with those of the base channel.')
         start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)
         pred = ReactionPredicate.yes_or_no(msg, ctx.author)
         try:
            await self.bot.wait_for('reaction_add', check = pred, timeout = 30.0)
         except asyncio.TimeoutError:
            return await msg.delete()

         await msg.delete()
         if pred.result is True:
            for channel in channels:
               async with self.config.channel(channel).highlights() as highlight:
                     highlight[str(ctx.author.id)] = base_config
            await ctx.send('done.')
         else:
            return await ctx.send('kden....')

      @highlight.command(name = 'clear')
      async def highlight_clear(self, ctx: commands.Context):
         """Clears your highlights."""

         await self.config.member(ctx.author).highlights.set([])
         await ctx.reply('Cleared your highlights.')

      @highlight.command(name = 'matches')
      async def highlight_matches(self, ctx: commands.Context, *, string: str):
         """Shows the highlights that match a given string.
         
         
         """

         guild_highlights, channel_highlights, member_config = (
            (await self.config.guild(ctx.guild).highlights()).get(str(ctx.author.id), []),
            (await self.config.channel(ctx.channel).highlights()).get(str(ctx.author.id), []),
            await self.config.member(ctx.author).all()
         )
         highlight_data = guild_highlights + channel_highlights
         message_data = await self.get_message_data(ctx.message)
         matches = await self.get_matches(highlight_data = highlight_data, message_data = message_data, config = member_config)
         description = []
         for d in highlight_data:
             if d['highlight'] in matches:
                description.append('✅ ' + d['highlight'])
             else:
                description.append('❌ ' + d['highlight'])

         embed = discord.Embed(
             title = 'Matches',
             description = '\n'.join(description),
             timestamp = datetime.datetime.utcnow(),
             colour = member_config.get('colour', 0x00ff00)
         ).set_footer(text = f'{len(matches)} matches')

         return await ctx.reply(embed = embed)

      @highlight.group(name = 'settings', aliases = ['set'], invoke_without_command = True)
      async def highlight_set(self, ctx: commands.Context):
         """Settings for Highlight."""
         await ctx.send_help(ctx.command.qualified_name)

      @highlight_set.command(name = 'cooldown', aliases = ['cd', 'ratelimit'])
      async def highlight_set_rate(self, ctx: commands.Context, rate: TimeConverter = None):
         """Sets the cooldown for being highlighted."""

         current = await self.config.member(ctx.author).cooldown()
         if rate is None:
            return await ctx.reply(f'Your current cooldown is {format_timespan(current)}.')
         if rate > 600 or rate < 1:
            return await ctx.reply('Cooldown cannot be more than 10 minutes or less than 1 second.')
         await self.config.member(ctx.author).cooldown.set(rate)
         await ctx.reply(f'Alright, your cooldown is now {format_timespan(rate)}.')

      @highlight_set.command(name = 'onlyoffline', aliases = ['onlyoff'])
      async def highlight_set_onlyoffline(self, ctx: commands.Context, yes_or_no: bool):
         """Only get highlighted while you are `Offline`."""

         current = await self.config.member(ctx.author).onlyoffline()
         if current == yes_or_no:
            return await ctx.reply(f'This is already {"enabled" if yes_or_no else "disabled"} for you....')
         await self.config.member(ctx.author).onlyoffline.set(yes_or_no)
         await ctx.reply(f'{"Enabled, you will now only get highlighted while you are `Offline`." if yes_or_no else "Disabled."}')

      @highlight_set.command(name = 'bots')
      async def highlight_set_bots(self, ctx: commands.Context, yes_or_no: bool):
         """Recieve highlights from messages sent by bots.
         
         This also highlights you for embeds, images are ignored even if you have image highlights enabled.
         """
         current = await self.config.member(ctx.author).bots()
         if current == yes_or_no:
            return await ctx.reply(f'This is already {"enabled" if yes_or_no else "disabled"} for you....')
         await self.config.member(ctx.author).bots.set(yes_or_no)
         await ctx.reply(f'{"Enabled, you can now recieve highlights from bots." if yes_or_no else "Disabled."}')

      @highlight_set.command(name = 'images', aliases = ['files'])
      async def highlight_set_images(self, ctx: commands.Context, yes_or_no: bool):
         """Get highlights from text in an image."""

         current = await self.config.member(ctx.author).images()
         if current == yes_or_no:
            return await ctx.reply(f'This is already {"enabled" if yes_or_no else "disabled"} for you....')
         await self.config.member(ctx.author).images.set(yes_or_no)
         await ctx.reply(f'{"Enabled, you can now recieve highlights from images." if yes_or_no else "Disabled."}')

      @highlight_set.command(name = 'colour', aliases = ['color'])
      async def highlight_set_colour(self, ctx: commands.Context, *, colour: commands.ColourConverter):
         """Sets the default embed colour."""

         await self.config.member(ctx.author).colour.set(colour.value)
         await ctx.reply('Updated your embed colour.')

      @highlight_set.command(name = 'show')
      async def highlight_set_show(self, ctx: commands.Context):
         """Shows your highlight settings."""

         data = await self.config.member(ctx.author).all()
         embed = discord.Embed(
            description = '\n'.join([
               f'Cooldown: {format_timespan(data["cooldown"])}',
               f'Only-Offline: {data["only_offline"]}',
               f'Images (beta): {data["images"]}',
               f'Bots: {data["bots"]}'
            ]),
            colour = data['embed_colour'],
            timestamp = datetime.datetime.utcnow()
         ).set_author(
            name = f'{ctx.author.display_name}\'s Highlight Settings',
            icon_url = (ctx.author.avatar or self.bot.user.avatar).url
         ).set_footer(
            text = f'Colour: #{hex(data["colour"])}'
         )
         await ctx.reply(embed = embed)

      @commands.group(name = 'highlightset', aliases = ['hlset'], invoke_without_command = True)
      @commands.has_permissions(manage_guild = True)
      async def highlightset(self, ctx: commands.Context):
          return await ctx.send_help(ctx.command.qualified_name)
       
      @highlightset.command(name = 'roles')
      async def highlightset_roles(self, ctx: commands.Context, roles: commands.Greedy[discord.Role] = None):
          current = self.settings.find_one({'guild_id': ctx.guild.id})['allowed_roles']
          if not roles:
             if not current:
                return await ctx.reply('You do not have any allowed roles, everyone can use this cog.')
             embed = discord.Embed(
                description = '\n'.join([ctx.guild.get_role(role).mention for role in current]),
                colour = discord.Colour.green(),
                timestamp = datetime.datetime.utcnow()
             ).set_author(
                name = f'{ctx.guild.name}\'s Highlight roles',
                icon_url = ctx.guild.icon.url
             )
             return await ctx.reply(embed = embed)
          
          async with self.config.guild(ctx.guild).allowed_roles() as current:
             for role in roles:
                 if role.id in current:
                    current.remove(role.id)
                 elif role.id not in current:
                    current.append(role.id)

          await ctx.invoke(ctx.command)