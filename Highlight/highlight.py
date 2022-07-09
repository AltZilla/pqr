import discord
import asyncio
import time
import logging
import datetime
import yaml

from io import BytesIO
from discord.ext import commands as dpy_commands
from redbot.core import commands, Config
from redbot.core.utils.chat_formatting import humanize_list, humanize_timedelta
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.predicates import ReactionPredicate
from .helpers import HighlightView, Matches, MessageRaw
from .converters import HighlightFlagResolver, TimeConverter
from typing import Union, List, Optional, Dict

log = logging.getLogger('red.cogs.Highlight')

async def allowed_check(ctx: commands.Context):
      allowed_roles = await ctx.cog.config.guild(ctx.guild).allowed_roles()
      if any(role.id in allowed_roles for role in ctx.author.roles) or allowed_roles == []:
         return True
      return False

class Highlight(commands.Cog):

      def __init__(self, bot: commands.Bot):
          self.bot = bot
          self.config = Config.get_conf(self, identifier = 1698497658475, force_registration = True)
          default_member = {
              'blocks': [],
              'cooldown': 60,
              'bots': False,
              'embeds': False,
              'images': False,
              'colour': discord.Colour.green().value
          }
          self.config.register_member(**default_member)
          self.config.register_global(
              cooldown__min = 30,
              cooldown__max = 600,
              len__min = 2,
              len__max = 50
          )
          self.config.register_guild(highlights = {}, allowed_roles = [])
          self.config.register_channel(highlights = {})
          self.last_seen = {}
          self.cooldowns = {} # TODO: Cache config
               
      @commands.Cog.listener('on_message')
      async def on_message(self, message: discord.Message):

         if not message.guild or isinstance(message.channel, discord.DMChannel):
            return

         if await self.bot.cog_disabled_in_guild(self, message.guild):
            return

         self.last_seen.setdefault(message.guild.id, {}).setdefault(message.author.id, {})[(message.channel.category or message.channel).id] = time.time()

         guild_highlights, channel_highlights, min_cd = (
            await self.config.guild(message.guild).highlights(),
            await self.config.channel(message.channel).highlights(),
            await self.config.cooldown.min()
         )

         # merge guild and channel highlights
         highlights = {}
         for d in (guild_highlights, channel_highlights):
             for member_id, hls in d.items():
                 highlights.setdefault(int(member_id), []).extend(hls)

         message_raw = await MessageRaw.from_message(message)

         history = [
               '**[<t:{timestamp}:T>] {author}:** {content} {attachments} {embeds}'.format(
                     timestamp = int(message.created_at.timestamp()),
                     author = message.author,
                     content = message.content[:500],
                     attachments = f' <Attachments {", ".join([f"[{index}]({attach.url})" for index, attach in enumerate(message.attachments)])}>' if message.attachments else '',
                     embeds = ' [embeds]' if message.embeds else ''
               )
             ]

         try: 
            async for msg in message.channel.history(limit = 4, before = message.created_at):
                history.insert(0, f'[<t:{int(msg.created_at.timestamp())}:T>] **{msg.author}:** {msg.content[:200]}')
         except (discord.Forbidden, AttributeError): # If its a voice channel, or we do can't view channel history, get history from cache instead.
            sorted_history = sorted(filter(lambda m: m.channel == message.channel and m.created_at < message.created_at, self.bot.cached_messages), key = lambda m: m.created_at, reverse = True)
            history.extend([f'[<t:{int(msg.created_at.timestamp())}:T>] **{msg.author}:** {msg.content[:200]}' for msg in sorted_history][:4])
            history.reverse()

         for member_id, highlight in highlights.items():
             member = message.guild.get_member(member_id)
             if not member:
                continue
             data = await self.config.member(member).all()
             cooldown = data['cooldown'] if data['cooldown'] > min_cd else min_cd
             if (
                (cd := self.cooldowns.get(message.guild.id, {}).get(member.id))
                and cd >= (time.time() - cooldown)
             ): 
                 continue
             last_seen = self.last_seen.get(message.guild.id, {}).get(member.id)
             if last_seen:   
                lsc, filtered = (
                   last_seen.get((message.channel.category or message.channel).id, 0),
                   list(filter(lambda t: t > (time.time() - 300), last_seen.values()))
                )
                if lsc > (time.time() - 300) or len(filtered) > 2:
                   continue
             matches = await Matches(data, highlight, message_raw).resolve()
             if not matches:
                continue
             if (
                not message.channel.permissions_for(member).read_message_history
                or not message.channel.permissions_for(member).read_messages
             ):
                continue
             if any(x.id in data['blocks'] for x in [message.author, message.channel]):
                continue
             self.cooldowns.setdefault(message.guild.id, {})[member.id] = time.time()

             embed = discord.Embed(
                  title = matches.format_title(),
                  description = '\n'.join(history),
                  timestamp = message.created_at,
                  colour = data['colour']
             ).add_field(
                  name = 'Source Message',
                  value = f'[Jump To]({message.jump_url})'
             ).set_footer(
                  text = 'Triggered At'
             )
             try:
                log.info(f'Sent Highlight to {member}, member was last highlighted at: {cd}')
                await member.send(
                     content = f'In **{message.guild.name}** {message.channel.mention}, you were mentioned with the highlighted word{"s" if len(matches) > 1 else ""} {matches.format_response()}.',
                     embed = embed,
                     view =  HighlightView(message, [d['highlight'] for d in highlight])
                )
             except discord.HTTPException:
                pass
             except Exception as e:
                log.error(f'Failed to Highlight {member} [GUILD]: {message.guild.name}.', exc_info = e)

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
      @commands.check_any(commands.check(allowed_check), dpy_commands.has_permissions(manage_guild = True))
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
            > `--channel`: Add the word(s) to a specified channel's highlights, this defaults to the current channel.
            > `--multiple`: Add multiple words to your highlights at once.
            > `--wildcard`: Attempts to search for bypasses fetching matches.
            > `--regex`: Add a Regular expression to your highlights. It is suggested you [learn regex](https://github.com/ziishaned/learn-regex) and [debug](https://regex101.com/) it first.
            > `--set <types...>`: Additional config for the added highlights. Valid Types: `bots`, `embeds` and `images`.
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

               if len(user_config) + len(word['words']) >= (limit := 10 if channel else 25):
                  return await ctx.reply('You have reached the maximum of `{limit}` highlights for this {type}.'.format(
                     limit = limit,
                     type = 'channel' if channel else 'guild'
                  ))
   
               data = [
                  {
                     'highlight': highlight, 
                     'channel': channel.id if channel else None, 
                     'type': word['type'],
                     'settings': word['settings']
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
            extra = f'highlights for {channel.mention}' if channel else 'guild highlights'
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
            yml_data = {'GUILD': {}, 'CHANNEL': {}}
            guild = (await self.config.guild(ctx.guild).highlights()).get(str(ctx.author.id), [])
            yml_data['GUILD'] = [
               {
                  highlight['highlight']: {
                     'settings': humanize_list(highlight.get('settings', [])),
                     'type': highlight.get('type', 'default')
                  }
                  for highlight in guild
               }
            ]
            channels = await self.config.all_channels()
            for channel_id, data in channels.items():
                if not (data := data.get('highlights', {}).get(str(ctx.author.id))):
                   continue
                channel = ctx.guild.get_channel(channel_id)
                if channel:
                   yml_data['CHANNEL'][channel.id] = [
                     {
                        highlight['highlight']: {
                           'settings': humanize_list(highlight.get('settings', [])), 
                           'type': highlight.get('type')
                        }
                     }
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

         async with self.config.guild(ctx.guild).highlights() as guild_highlights:
            guild_highlights[str(ctx.author.id)] = []

         channels = await self.config.all_channels()
         for channel, data in channels.items():
             if data.get('highlights', {}).get(str(ctx.author.id)):
                async with self.config.channel_from_id(channel).highlights() as channel_highlights:
                    channel_highlights[str(ctx.author.id)] = []

         await ctx.reply('Cleared your highlights.')

      @highlight.command(name = 'matches')
      async def highlight_matches(self, ctx: commands.Context, *, string: str):
         """Shows the highlights that match a given string."""

         guild_highlights, channel_highlights, member_config = (
            (await self.config.guild(ctx.guild).highlights()).get(str(ctx.author.id), []),
            (await self.config.channel(ctx.channel).highlights()).get(str(ctx.author.id), []),
            await self.config.member(ctx.author).all()
         )
         highlight_data = guild_highlights + channel_highlights
         matches = await Matches(member_config, highlight_data).resolve(ctx.message)
         description = []
         print(matches._matches)
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

      @highlight.group(name = 'settings', aliases = ['set'], autohelp = True, invoke_without_command = True)
      async def highlight_set(self, ctx: commands.Context):
         """Settings for Highlight."""

      @highlight_set.command(name = 'cooldown', aliases = ['cd', 'ratelimit'])
      async def highlight_set_rate(self, ctx: commands.Context, rate: TimeConverter = None):
         """Sets the cooldown for being highlighted."""

         current = await self.config.member(ctx.author).cooldown()
         if rate is None:
            return await ctx.reply(f'Your current cooldown is **{humanize_timedelta(seconds = current)}**.')
         if rate > 600 or rate < 1:
            return await ctx.reply('Cooldown cannot be more than 10 minutes or less than 1 second.')
         await self.config.member(ctx.author).cooldown.set(rate)
         await ctx.reply(f'Alright, your cooldown is now {humanize_timedelta(seconds = rate)}.')

      async def _toggle_settings(self, ctx: commands.Context, name: str, yes_or_no: bool):
         async with self.config.member(ctx.author).all() as conf:
            if yes_or_no == conf[name]:
               return await ctx.reply(f'This is already {"enabled" if yes_or_no else "disabled"} for you....')
            conf[name] = yes_or_no
            return await ctx.reply(f'{"Enabled, " + f"you can now recieve highlights from {name}." if yes_or_no else "Disabled."}')
            
      @highlight_set.command(name = 'bots')
      async def highlight_set_bots(self, ctx: commands.Context, yes_or_no: bool):
         """Recieve highlights from messages sent by bots.
         """
         await self._toggle_settings(ctx, 'bots', yes_or_no)

      @highlight_set.command(name = 'embeds')
      async def highlight_set_embeds(self, ctx: commands.Context, yes_or_no: bool):
         """Recieve highlights from embeds.

         This checks every field except for `type` and `color`, urls are ignored.
         This only really does smt when you have bot highlights enabled.
         """
         await self._toggle_settings(ctx, 'embeds', yes_or_no)

      @highlight_set.command(name = 'images', aliases = ['files'])
      async def highlight_set_images(self, ctx: commands.Context, yes_or_no: bool):
         """Get highlights from text in an image.
         """
         await self._toggle_settings(ctx, 'images', yes_or_no)

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
               f'Cooldown: {humanize_timedelta(seconds = (data["cooldown"]))}',
               f'Bots: {data["bots"]}',
               f'Embeds: {data["embeds"]}',
               f'Images (beta): {data["images"]}'
            ]),
            colour = data['colour'],
            timestamp = datetime.datetime.utcnow()
         ).set_author(
            name = f'{ctx.author.display_name}\'s Highlight Settings',
            icon_url = (ctx.author.avatar or self.bot.user.avatar).url
         ).set_footer(
            text = f'Colour: #{hex(data["colour"])}'
         )
         await ctx.reply(embed = embed)

      @highlight_set.command(name = 'roles')
      @commands.has_permissions(manage_guild = True)
      async def highlightset_roles(self, ctx: commands.Context, roles: commands.Greedy[discord.Role]):
           async with self.config.guild(ctx.guild).allowed_roles() as current:
               for role in roles:
                  if role.id in current:
                     current.remove(role.id)
                  elif role.id not in current:
                     current.append(role.id)
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
