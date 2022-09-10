import json
import discord
import asyncio
import time
import logging
import datetime
import multiprocessing as mp

from io import BytesIO
from discord.ext import commands as dpy_commands
from redbot.core import commands, Config
from redbot.core.utils import AsyncIter
from redbot.core.utils.chat_formatting import humanize_list, humanize_timedelta
from redbot.core.utils.menus import start_adding_reactions, menu
from redbot.core.utils.predicates import ReactionPredicate
from .helpers import (
      HighlightView, 
      HighlightHandler,
      Matches
)
from .converters import (
      HighlightFlagResolver
)
from .menus import ChannelShowMenu

from typing import Union, Optional, Literal

log = logging.getLogger('red.cogs.Highlight')

async def allowed_check(ctx: commands.Context):
      allowed_roles = await ctx.cog.config.guild(ctx.guild).allowed_roles()
      if any(role.id in allowed_roles for role in ctx.author.roles) or allowed_roles == []:
         return True
      return False

class Highlight(HighlightHandler, commands.Cog):

      def __init__(self, bot: commands.Bot):
          self.bot = bot
          self.config = Config.get_conf(self, identifier = 1698497658475, force_registration = True)
          self.default_member = {
              'blocks': [],
              'cooldown': 60,
              'bots': False,
              'embeds': False,
              'edits': False,
              'colour': discord.Colour.green().value,
              'logs': []
          }
          self.config.register_member(**self.default_member)
          self.config.register_global(
              cooldown__min = 30,
              cooldown__max = 600,
              len__min = 2,
              len__max = 50
          )
          self.config.register_guild(highlights = {}, allowed_roles = [])
          self.config.register_channel(highlights = {}, synced_with = {})
          self.last_seen = {}
          self.cooldowns = {}
          self.blacklist = {} # member_id -> Data

          self.re_pool = mp.Pool()

      async def red_delete_data_for_user(self, *, requester: Literal["discord_deleted_user", "owner", "user", "user_strict"], user_id: int):
         ...

      async def cog_load(self):
         asyncio.create_task(self.generate_cache())
         
      @commands.Cog.listener('on_message')
      async def on_message(self, message: discord.Message):

         if not message.guild or isinstance(message.channel, discord.DMChannel):
            return

         if await self.bot.cog_disabled_in_guild(self, message.guild):
            return

         #if message.author.bot:
          #  return

         self.last_seen.setdefault(message.guild.id, {}).setdefault(getattr(message.interaction, 'user', message.author).id, {})[(message.channel.category or message.channel).id] = time.time()

         highlights = await self.get_highlights_for_message(message=message)

         history = [
               '**[<t:{timestamp}:T>] {author}:** {content} {attachments} {embeds}'.format(
                     timestamp = int(message.created_at.timestamp()),
                     author = message.author,
                     content = message.content[:500],
                     attachments = f' <Attachments {", ".join([f"[{index}]({attach.url})" for index, attach in enumerate(message.attachments, 1)])}>' if message.attachments else '',
                     embeds = ' [embeds]' if message.embeds else ''
               )
         ]

         try: 
            async for msg in message.channel.history(limit = 4, before = message.created_at):
                history.insert(0, f'[<t:{int(msg.created_at.timestamp())}:T>] **{msg.author}:** {msg.content[:200]}')
         except (discord.NotFound, discord.Forbidden, AttributeError): # If its a voice channel, or we do can't view channel history, get history from cache instead.
            sorted_history = sorted(filter(lambda m: m.channel == message.channel and m.created_at < message.created_at, self.bot.cached_messages), key = lambda m: m.created_at, reverse = True)
            history.extend([f'[<t:{int(msg.created_at.timestamp())}:T>] **{msg.author}:** {msg.content[:200]}' for msg in sorted_history][:4])
            history.reverse()
            
         async for member_id, highlight in AsyncIter(highlights.items(), steps = 1000):
             member = message.guild.get_member(member_id)
             if not member:
                continue
             data = self.get_member_config(member)
             cooldown = self._check_cooldown(seconds = data['cooldown'])
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
             matches = await Matches._resolve(self, member, highlights = highlight, message = message)
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

             embed = matches.create_embed(history = history, message = message, settings = data)
             try:
                await member.send(
                     content = f'In **{message.guild.name}** {message.channel.mention}, you were mentioned with the highlighted word{"s" if len(matches) > 1 else ""} {matches.format_response()}.',
                     embed = embed,
                     view =  HighlightView(message, [hl['highlight'] for hl in highlight])
                )
                async with self.config.member(member).logs() as logs:
                  logs.append(
                     {
                        'channel_id': message.channel.id,
                        'highlighted_by': message.author.id,
                        'embed': embed.to_dict(),
                        'highlighted_at': int(message.created_at.timestamp())
                     }
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
            - Sending a message.
            - Adding / Removing a reaction.
            - Trigger Typing.

         If you were last seen in more than 2 categories, you will not get highlighted for the entire guild.
         """
         await self.handle_highlight_update(ctx, word, action = None)

      @highlight.group(name = 'channel', autohelp = True)
      async def highlight_channel(self, ctx: commands.Context):
         """Manage channel-specific highlights."""
         pass

      @highlight_channel.command(name = 'add')
      async def highlight_channel_add(self, ctx: commands.Context, channel: Optional[Union[discord.TextChannel, discord.VoiceChannel]], *, word: HighlightFlagResolver):
         """Add words to your channel highlights.

         You can add a maximum of 10 highlights per channel, there is a limit of **20** channels you can add highlights to.

         **Flags:**
            > `--multiple`: Add multiple words to your highlights at once.
            > `--wildcard`: Attempts to search for bypasses fetching matches.
            > `--regex`: Add a Regular expression to your highlights. It is suggested you [learn regex](https://github.com/ziishaned/learn-regex) and [debug](https://regex101.com/) it first.
            > `--set <types...>`: Additional config for the added highlights. Valid Types: `bots`, `embeds`.
         """
         await self.handle_highlight_update(ctx, word, action = 'add', channel = channel or ctx.channel)

      @highlight_channel.command(name = 'remove')
      async def highlight_channel_remove(self, ctx: commands.Context, channel: Optional[Union[discord.TextChannel, discord.VoiceChannel]], *, word: HighlightFlagResolver):
         """Removes word(s) from your channel highlights."""

         await self.handle_highlight_update(ctx, word, action = 'remove', channel = channel or ctx.channel)

      @highlight_channel.command(name = 'sync')
      async def highlight_sync(self, ctx: commands.Context, base_channel: Union[discord.TextChannel, discord.VoiceChannel], channels_and_categories: commands.Greedy[Union[discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel]]):
         """Syncs your highlights from one channel to multiple others.
         
         This will replace the highlights of all the channels mentioned in `<channels_and_categories>` with those of the base channel.
         
         **Arguments:**
            - `<base_channel>`: The channel to sync highlights from.
            - `<channels_and_categories>`: The channels to sync highlights to, if a category is passed, highlights are synced with all the channels in that category. Including voice channels.
            
         """
         return await ctx.send(
            'This command has been temporarily disabled.'
         )
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

      @highlight.command(name = 'add', aliases = ['+'])
      async def highlight_add(self, ctx: commands.Context, *, word: HighlightFlagResolver):
         """Add words to your guild highlights.

         You can add a maximum of 25 highlights per guild.

         **Flags:**
            > `--multiple`: Add multiple words to your highlights at once.
            > `--wildcard`: Attempts to search for bypasses fetching matches.
            > `--regex`: Add a Regular expression to your highlights. It is suggested you [learn regex](https://github.com/ziishaned/learn-regex) and [debug](https://regex101.com/) it first.
            > `--set <types...>`: Additional config for the added highlights. Valid Types: `bots`, `embeds`.
         """
         await self.handle_highlight_update(ctx, word, action = 'add')
      
      @highlight.command(name = 'remove', aliases = ['-'])
      async def highlight_remove(self, ctx: commands.Context, *, word: HighlightFlagResolver):
         """Removes word(s) from your guild highlights."""

         await self.handle_highlight_update(ctx, word, action = 'remove')

      @highlight.command(name = 'ignore', aliases = ['block'])
      async def highlight_ignore(self, ctx: commands.Context, blocks: commands.Greedy[Union[discord.Member, discord.TextChannel, discord.VoiceChannel]]):
         """Blocks a Member or Channel from Highlighting you."""

         await self.handle_block_update(ctx, blocks, 'add')

      @highlight.command(name = 'unignore', aliases = ['unblock'])
      async def highlight_unignore(self, ctx: commands.Context, blocks: commands.Greedy[Union[discord.Member, discord.TextChannel, discord.VoiceChannel]]):
         """Unblocks a Member or Channel from Highlighting you."""

         await self.handle_block_update(ctx, blocks, 'remove')

      @highlight.command(name = 'show', aliases = ['list', 'display'])
      async def highlight_show(self, ctx: commands.Context, channel: Optional[Union[discord.TextChannel, discord.VoiceChannel]]):
         """Shows your current highlights."""

         all_highlights = await self.get_all_member_highlights(ctx.author)
         await ChannelShowMenu(ctx, all_highlights, self.member_config.get(ctx.guild.id).get(ctx.author.id, {}).get('blocks', []), ).send(start_value = getattr(channel, 'id', None))

      @highlight.command(name = 'clear')
      async def highlight_clear(self, ctx: commands.Context):
         """Clears your highlights."""

         confirm_message = await ctx.send('Are you sure you want to clear your highlights? This removes all your guild & channel highlights and cannot be reverted.')
         start_adding_reactions(confirm_message, ReactionPredicate.YES_OR_NO_EMOJIS)

         pred = ReactionPredicate.yes_or_no(confirm_message, ctx.author)
         try:
            await self.bot.wait_for('reaction_add', check = pred, timeout = 30.0)
            asyncio.create_task(
               confirm_message.clear_reactions()
            )
         except asyncio.TimeoutError:
            return await confirm_message.edit(content = 'Operation cancelled.')
         
         if not pred.result is True:
            return await confirm_message.edit(content = 'Operation cancelled.')

         deleted_count = 0
         async with self.config.guild(ctx.guild).highlights() as guild_highlights:
            if h := guild_highlights.get(str(ctx.author.id)):
               del guild_highlights[str(ctx.author.id)]
               deleted_count += len(h)

         channels = await self.config.all_channels()
         for channel, data in channels.items():
             if h := data.get('highlights', {}).get(str(ctx.author.id)):
                async with self.config.channel_from_id(channel).highlights() as channel_highlights:
                    del channel_highlights[str(ctx.author.id)]
                    deleted_count += len(h)

         await confirm_message.edit(f'Removed **{deleted_count}** highlights from you.')
         await self.generate_cache()

      @highlight.command(name = 'matches')
      async def highlight_matches(self, ctx: commands.Context, *, string: str):
         """Shows the highlights that match a given string.
         
         Currently this only shows matches for guild highlights and ignores channel highlights."""

         member_config, highlights = (
            self.get_member_config(ctx.author),
            (await self.get_all_member_highlights(ctx.author)).get(ctx.guild.id, [])
         )
         if not highlights:
            return await ctx.send('You have no guild highlights, what do u want me to find matches for....')

         matches = await Matches._resolve(self, highlights, ctx.message)
         description = []
         for d in highlights:
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

      @highlight.command(name = 'export')
      async def highlight_export(self, ctx: commands.Context):
         """Export your highlights to a JSON file.
         """
         highlights = await self.get_all_member_highlights(member = ctx.author)

         _file = BytesIO(json.dumps(highlights, indent = 3).encode())
         await ctx.send(file = discord.File(_file, 'highlights.json'))

      @highlight.command(name = 'logs', enabled = False)
      async def highlight_logs(self, ctx: commands.Context):
         logs = self.get_member_config(ctx.author)['logs']
         pages = []
         for data in logs:
               pages.append(
                  discord.Embed.from_dict(data['embed']).set_footer(text = getattr(ctx.guild.get_channel(data['channel_id']), 'name', 'deleted channel'))
               )

         await menu(ctx, pages)

      @highlight.group(name = 'settings', aliases = ['set'], autohelp = True, invoke_without_command = True)
      async def highlight_set(self, ctx: commands.Context):
         """Settings for Highlight."""

      @highlight_set.command(name = 'cooldown', aliases = ['cd', 'ratelimit'])
      async def highlight_set_rate(self, ctx: commands.Context, *, rate: commands.TimedeltaConverter = None):
         """Sets the cooldown for being highlighted.
         
         Min / Max = 30 / 600 Seconds :thumbsup:
         """

         current = await self.config.member(ctx.author).cooldown()
         if rate is None:
            return await ctx.reply(f'Your current cooldown is **{humanize_timedelta(seconds = current)}**.')
         rate = self._check_cooldown(seconds = rate.total_seconds())
         await self.config.member(ctx.author).cooldown.set(rate)
         await ctx.reply(f'Alright, your cooldown is now **{humanize_timedelta(seconds = rate)}**.')

      async def _toggle_settings(self, ctx: commands.Context, name: str, yes_or_no: bool):
         raise commands.DisabledCommand('Setting commands have been temporarily disabled :thumbsup:')

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
               f'Bots (disabled): {data["bots"]}',
               f'Embeds (disabled): {data["embeds"]}',
               f'Edits (disabled + soon:tm:): {data["edits"]}'
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