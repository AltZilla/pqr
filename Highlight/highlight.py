import json
import discord
import asyncio
import time
import logging
import datetime
import tabulate
import TagScriptEngine as tse

from io import BytesIO
from discord.ext import commands as dpy_commands
from redbot.core import commands, Config
from redbot.core.utils import AsyncIter
from redbot.core.utils.chat_formatting import humanize_list, humanize_timedelta, box
from redbot.core.utils.menus import start_adding_reactions, menu
from redbot.core.utils.predicates import ReactionPredicate
from .views import SimpleMenu

from .helpers import (
      HighlightView,
      HighlightHandler,
      Matches
)
from .converters import (
      HighlightFlagResolver
)

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
         self.config.register_member(
            blocks = [],
            cooldown = 60,
            bots = False,
            embeds = False,
            edits = False,
            colour = discord.Colour.green().value,
            logs = [],
            ### last seen settings
            last_seen__messages = True,
            last_seen__reactions = True,
            last_seen__typing = True,
            last_seen__offline = False,
            last_seen__category_threshold = 2,
            last_seen__timeout = 300,
            ### format settings
            format__content = 'In **{guild(name)}** {channel(mention)}, you were mentioned with the highlight {if({matches(count)} > 1):words|word} {matches(format_response)}',
            format__history = '[<t:{message(timestamp)}:T>] **{author}**: {message(content)}',
            ### wildcard settings
            wildcard__max_repetitions = 2,
            wildcard__bypass_chars = ['_', '-', ' '],
            wildcard__max_bypass = 5
         )
         self.config.register_global(
            cooldown__min = 30,
            cooldown__max = 600
         )
         self.config.register_guild(highlights = {}, allowed_roles = [])
         self.config.register_channel(highlights = {}, synced_with = {})
         self.last_seen = {}
         self.cooldowns = {}
         self.blacklist = {} # member_id -> Data

         self.tagscript_interpreter = tse.AsyncInterpreter(
            [
               tse.SubstringBlock(), 
               tse.StrictVariableGetterBlock(),
               tse.AssignmentBlock(),
               tse.StrfBlock(),
               tse.IfBlock()
            ]
         )
         # self.re_pool = mp.Pool()

      async def red_delete_data_for_user(self, *, requester: Literal["discord_deleted_user", "owner", "user", "user_strict"], user_id: int):
         ...

      async def cog_load(self):
         asyncio.create_task(self.generate_cache())
         
      @commands.Cog.listener('on_message')
      async def on_message(self, message: discord.Message):

         if not message.guild or isinstance(message.channel, (discord.DMChannel, discord.Thread)):
            return

         if await self.bot.cog_disabled_in_guild(self, message.guild):
            return

         self.mark_last_seen(getattr(message.interaction, 'user', message.author), message.channel, 'message')

         highlights, history = await self.get_highlights_for_message(message=message), None

         # f'[<t:{int(msg.created_at.timestamp())}:T>] **{msg.author}:** {msg.content[:200]}'

         members_highlighted = []
         async for member_id, highlight in AsyncIter(highlights.items(), steps = 1000):
            member = message.guild.get_member(member_id)
            if not member or self.blacklist.get(member.id):
               continue
            data = self.get_member_config(member)
            if (
               (cd := self.cooldowns.get(message.guild.id, {}).get(member.id))
               and cd >= (time.time() - self._check_cooldown(seconds = data['cooldown']))
            ):
               continue
            last_seen, ls_conf = self.last_seen.get(message.guild.id, {}).get(member.id), data['last_seen']
            if last_seen:
               lsc, filtered = (
                  last_seen.get((message.channel.category or message.channel).id, 0),
                  list(filter(lambda t: t > (time.time() - ls_conf['timeout']), last_seen.values()))
               )
               if lsc > (time.time() - ls_conf['timeout']) or len(filtered) > ls_conf['category_threshold']:
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
            # fetch history only if sm1 has been highlight
            if history is None:
               try: 
                  history = [msg async for msg in message.channel.history(limit = 5)][::-1]
               except (discord.NotFound, discord.Forbidden, AttributeError): # If its a voice channel, or we do can't view channel history, get history from cache instead.
                  history = list(sorted(filter(lambda m: m.channel == message.channel and m.created_at <= message.created_at, self.bot.cached_messages), key = lambda m: m.created_at))[:5]

            resp = await matches.response_mapping(history = history)
            # f'In **{message.guild.name}** {message.channel.mention}, you were mentioned with the highlighted word{"s" if len(matches) > 1 else ""} {matches.format_response()}.'
            try:
               await member.send(**resp)
               members_highlighted.append(member)
               async with self.config.member(member).logs() as logs:
                  logs.append(
                     {
                        'channel_id': message.channel.id,
                        'highlighted_by': message.author.id,
                        'matches': matches._matches,
                        'description': resp['embed'].description,
                        'highlighted_at': int(message.created_at.timestamp())
                     }
                  )
            except discord.HTTPException:
               pass
            except Exception as e:
               log.error(f'Failed to Highlight {member} [GUILD]: {message.guild.name}.', exc_info = e)
         if members_highlighted and message.channel.category_id in [975215943506624532, 722753720248565770, 719202787904323635, 817270098427117588, 753339882641817600, 738129181967253584]:
            embed = discord.Embed(
               title = 'Private Channel Highlight',
               description = '\n'.join([f'> {m.mention} - {m}' for m in members_highlighted]),
               timestamp = datetime.datetime.utcnow(),
               colour = discord.Colour.red()
            )
            embed.add_field(
               name = 'Message',
               value = history[-1].content[:500]
            )
            embed.set_footer(text = message.channel.name, icon_url = (message.guild.icon or message.author.avatar).url)
            await self.send_alert(embed = embed)

      @commands.Cog.listener('on_typing')
      async def on_typing(self, channel, user, when):
         self.mark_last_seen(user, channel, 'typing')

      @commands.Cog.listener('on_reaction_add')
      @commands.Cog.listener('on_reaction_remove')
      async def on_reaction(self, reaction: discord.Reaction, user: Union[discord.User, discord.Member]):
         self.mark_last_seen(user, reaction.message.channel, 'reaction')

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

         highlights, conf = await self.get_all_member_highlights(ctx.author), self.get_member_config(ctx.author)
         # await ChannelShowMenu(ctx, all_highlights, self.get_member_config(ctx.author)['blocks']).send(start_value = getattr(channel, 'id', None))

         guild_ = highlights.pop(ctx.guild.id, None)
         if not guild_:
            return await ctx.send('You have to guild highlights :thumbsup:')

         embed = discord.Embed(
            title = 'You\'re currently tracking the following words',
            description = box(tabulate.tabulate(guild_, headers = 'keys', tablefmt = 'pretty'), lang = 'prolog'),
            color = conf['colour']
         )
         if (user_blocks := [self._ctx.guild.get_member(user).mention for user in conf['blocks'] if self._ctx.guild.get_member(user) != None]):
            embed.add_field(name = 'Ignored Users', value = '\n'.join(user_blocks), inline = False)
            
         if (channel_blocks := [self._ctx.guild.get_channel(channel).mention for channel in conf['blocks'] if self._ctx.guild.get_channel(channel) != None]):
            embed.add_field(name = 'Ignored Channels', value = '\n'.join(channel_blocks), inline = False)

         pages, select_options = (
            [embed], [discord.SelectOption(label = ctx.guild.name, description = f'Highlight Count -> {len(guild_)}', value = 0)]
         )
         for channel_id, highlight in highlights.items():
            if highlight and (channel := ctx.guild.get_channel(channel_id)):
               embed = discord.Embed(
                     title = f'Your current highlights in # {getattr(channel, "name", "Unkown Channel")}'[:50],
                     description = box(tabulate.tabulate(highlight, headers = 'keys', tablefmt = 'pretty'), lang = 'prolog'),
                     color = conf['colour']
               )
               pages.append(embed)
               select_options.append(
                  discord.SelectOption(label = '# ' + getattr(channel, 'name', 'Unknown Channel'), description = f'Highlight Count -> {len(highlight)}', value = pages.index(embed))
               )
             
         menu = SimpleMenu(pages = pages, use_select_menu = True)
         menu.select_menu.options = select_options[:25]
         await menu.start(ctx)
         
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
         """

         member_config, highlights = (
            self.get_member_config(ctx.author),
            await self.get_all_member_highlights(ctx.author)
         )
         if not highlights:
            return await ctx.send('You have no guild highlights :thumbsup:')

         pages, options = [], []
         for _id, highlight in highlights.items():
            matches, guild, channel = await Matches._resolve(self, ctx.author, highlight, ctx.message), self.bot.get_guild(_id), self.bot.get_channel(_id)
            description = []
            for d in highlight:
               if d['highlight'] in matches:
                  description.append('✅ ' + d['highlight'])
               else:
                  description.append('❌ ' + d['highlight'])
            embed = discord.Embed(
               title = f'Matches ( #{getattr(channel, "name", "Unknown Channel")} )' if not guild else "Matches",
               description = '\n'.join(description),
               timestamp = datetime.datetime.utcnow(),
               colour = member_config['colour']
            ).set_footer(text = f'{len(matches)} matches')
            pages.append(embed)
            options.append(
               discord.SelectOption(label = f'# {getattr(channel, "name", "Unknown Channel")}' if not guild else getattr(guild, "name", "Unknown Guild"), description = f'Matches -> {len(matches)}', value = pages.index(embed))
            )

         menu = SimpleMenu(pages = pages, use_select_menu = True)
         menu.select_menu.options = options[:25]
         await menu.start(ctx)

      @highlight.command(name = 'export')
      async def highlight_export(self, ctx: commands.Context):
         """Export your highlights to a JSON file.
         """
         highlights = await self.get_all_member_highlights(member = ctx.author)

         _file = BytesIO(json.dumps(highlights, indent = 3).encode())
         await ctx.send(file = discord.File(_file, 'highlights.json'))

      @highlight.group(name = 'settings', aliases = ['set'], autohelp = True, invoke_without_command = True)
      async def highlight_set(self, ctx: commands.Context):
         """Settings for Highlight."""
         return await ctx.send_help()

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
         await self.generate_cache()

      async def _toggle_settings(self, ctx: commands.Context, name: str, yes_or_no: bool):

         async with self.config.member(ctx.author).all() as conf:
            if yes_or_no == conf[name]:
               return await ctx.reply(f'This is already {"enabled" if yes_or_no else "disabled"} for you....')
            conf[name] = yes_or_no
            await ctx.reply(f'{"Enabled, " + f"you can now recieve highlights from {name}." if yes_or_no else "Disabled."}')
         await self.generate_cache()
            
      @highlight_set.command(name = 'bots')
      async def highlight_set_bots(self, ctx: commands.Context, yes_or_no: bool):
         """Recieve highlights from messages sent by bots.
         """
         await self._toggle_settings(ctx, 'bots', yes_or_no)

      @highlight_set.command(name = 'embeds', enabled = False)
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

      @highlight_set.group(name = 'response', autohelp = True)
      async def highlight_response(self, ctx: commands.Context):
         """[Soon] Configure the highlight-message.
         
         This uses TagScript :thumbsup:"""

      @highlight_response.command(name = 'content', enabled = False)
      async def highlight_response_content(self, ctx: commands.Context, *, body: str):
         """That lil message above the embed"""
         if len(body) > 250:
            return await ctx.send('`body` cannot be more than 250 characters long.')

         override_config = self.default_member.copy()
         override_config['format']['content'] = body

         matches = await self.create_matches(ctx.author, ctx.message, None, dummy = True)
         resp = await matches.response_mapping([msg async for msg in ctx.history(limit = 5)][::-1], override_config = override_config)
         await ctx.send(
            resp['content']
         )

      @highlight_response.command(name = 'history', enabled = False)
      async def highlight_response_history(self, ctx: commands.Context, *, body: str):
         """The history format :thumbsup:"""
         if len(body) > 250:
            return await ctx.send('`body` cannot be more than 250 characters long.')

         override_config = self.default_member.copy()
         override_config['format']['history'] = body

         matches = await self.create_matches(ctx.author, ctx.message, None, dummy = True)
         resp = await matches.response_mapping([msg async for msg in ctx.history(limit = 5)][::-1], override_config = override_config)
         await ctx.send(
            embed = resp['embed']
         )

      @highlight_set.command(name = 'show')
      async def highlight_set_show(self, ctx: commands.Context):
         """Shows your highlight settings."""

         data = self.get_member_config(ctx.author)
         _ansi = lambda word, s1 = 1, s2 = 1, s3 = 34: f'[{s1};{s2};{s3}m[{word}][0m'

         def bool_str(bool_obj: bool, ansi = True):
            ret = 'Enabled' if bool_obj else 'Disabled'
            if ansi:
               ret = _ansi(ret, 1, 1, 36 if bool_obj else 31)
            return ret

         last_seen, format, wildcard = data['last_seen'], data['format'], data['wildcard']
         pages = [
            discord.Embed(
               description = '\n'.join([
                  f'------- Highlight Settings ------',
                  f'Cooldown:          {_ansi(humanize_timedelta(seconds = (data["cooldown"])))}',
                  f'Bots:              {bool_str(data["bots"])}',
                  f'Embeds:            {bool_str(data["embeds"])}',
                  f'Edits:             {bool_str(data["edits"])}'
               ]
            )),
            discord.Embed(
               description = '\n'.join([
                  f'--------- Last-Seen Settings --------',
                  f'Cache Timeout:       {_ansi(humanize_timedelta(seconds = (last_seen["timeout"])))}',
                  f'Messages:            {bool_str(last_seen["messages"])}',
                  f'Reactions:           {bool_str(last_seen["reactions"])}',
                  f'Typing:              {bool_str(last_seen["typing"])}',
                  f'Category Threshold:  {_ansi(last_seen["category_threshold"])}'
               ]
            )),
            discord.Embed(
               description = '\n'.join([
                  f'--------- Wildcard Settings --------',
                  f'Max Char Repetitions:       {_ansi(wildcard["max_repetitions"])}',
                  f'Bypass Characters:          {_ansi("".join(wildcard["bypass_chars"]))}',
                  f'Max Char Bypasses:          {_ansi(wildcard["max_bypass"])}'
               ]
            )),
            discord.Embed(title = 'Response Format',)
               .add_field(name = 'Content', value = box(format['content'], lang = 'md'), inline = False)
               .add_field(name = 'History', value = box(format['history'], lang = 'md'), inline = False)
         ]
         for page in pages:
            page.description = box(page.description, lang = 'ansi') if page.description else None
            page.colour = data['colour']
            page.set_footer(text = f'Colour: #{hex(data["colour"])}')

         menu = SimpleMenu(pages = pages, use_select_menu=True, use_select_only=True)
         menu.select_menu.options = [
            discord.SelectOption(label = 'Highlight Settings', value = 0), 
            discord.SelectOption(label = 'Last-Seen Settings', value = 1),
            discord.SelectOption(label = 'Wildcard Settings', value = 2),
            discord.SelectOption(label = 'Response Format', value = 3),
         ]
         await menu.start(ctx)

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