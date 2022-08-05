import asyncio
import functools
import re
import discord

from . import TRADES_GUILD_ID
from redbot.core import commands, Config
from discord import app_commands as app
from fuzzywuzzy import process
from typing import Literal, Optional, Tuple, Union, List
from .reminder import Reminder
from .components import EmbedPeekView, PossibleMentionsView

@app.context_menu(name = "Possible Mentions")
async def _possible_mentions(interaction: discord.Interaction, message: discord.Message):
    result: List[Tuple[discord.Object, int]] = []
    string = message.clean_content
    await interaction.response.defer(ephemeral=True)

    async def _process(querry, choices, t = 'extract', limit = 5):
        loop = asyncio.get_event_loop()
        if t == 'extract':
           partial = functools.partial(process.extract, querry, choices, limit = limit)
        else:
           partial = functools.partial(process.extractOne, querry, choices)
        return await loop.run_in_executor(
            None, partial
        )

    if message.embeds:
        def clean(d):
            d = list(d)
            for t in d:
                if not isinstance(t, str):
                   d.remove(t)
            return d

        for embed in map(lambda e: e.to_dict(), message.embeds):
            for _ in embed.values():
                if isinstance(_, str):
                    string += ' ' + _
                elif isinstance(_, dict):
                    string += ' ' + ' '.join(clean(_.values()))
                elif isinstance(_, list):
                    string += ' ' + ' '.join([' '.join(clean(field.values())) for field in _])

    to_check = message.guild.members + message.guild.roles + [channel for channel in message.guild.channels if channel.permissions_for(interaction.user).view_channel]

    def _check(obj):
        for item in result:
            if item[0] == obj:
               return False
        return True

    for _id in re.findall(r'(?P<id>[0-9]{15,20})', string):
        obj_id, score = await _process(_id, map(lambda o: o.id, to_check), 'extractOne')
        obj = discord.utils.get(to_check, id = obj_id)
        if _check(obj):
           result.append((obj, score))
    
    for _tag in re.findall(r'.{1,50}#[0-9]{4}', string):
        obj, score = await _process(_tag, message.guild.members, 'extractOne')
        if _check(obj):
           result.append((obj, score))

    remaining = 10 - len(result)

    if remaining > 0:
       _extracted = await _process(string, map(lambda m: m.name, to_check), limit = remaining)
       for name, score in _extracted:
           obj = discord.utils.get(to_check, name = name)
           if _check(obj):
              result.append((obj, score))

    data = {
        'members': [r for r in result if isinstance(r[0], discord.Member)][:5],
        'roles': [r for r in result if isinstance(r[0], discord.Role)][:5],
        'channels': [r for r in result if any(isinstance(r[0], t) for t in [discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel])][:5]
    }
    await PossibleMentionsView(interaction.user, **data).start(interaction)

class Trades(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier = 719180744311701505)
        self.config.register_guild(
            vote__role = None
        )
        self.config.register_member(
            vote__reminders = True
        )
        self._reminder = Reminder(self)

        ### for now...
        self.bot.tree.add_command(_possible_mentions)

    async def cog_check(self, ctx: commands.Context) -> bool:
        return ctx.guild.id == TRADES_GUILD_ID

    @commands.Cog.listener('on_member_update')
    async def _vote_reminder_event(self, before: discord.Member, after: discord.Member):
        if after.guild.id != TRADES_GUILD_ID or before.roles == after.roles or after.bot:
           return
        if await self.config.member(after).vote.reminders() == False:
           return
        voter_role = before.guild.get_role((await self.config.guild(after.guild).vote.role()))
        if not voter_role:
           return

        if voter_role in before.roles and voter_role not in after.roles:
           self._reminder.remind(after)

    @commands.group(name = 'votereminder', aliases = ['vrm'], invoke_without_command = True)
    async def _vote_reminder(self, ctx: commands.Context, on_or_off: bool):
        """Base command for Vote Reminders

        **Arguments:**
          - `on_or_off`: Whether you want to be reminded to vote again or not. 
        """
        async with self.config.member(ctx.author).vote() as conf:
            if conf['reminders'] == on_or_off:
               return await ctx.reply('Vote Reminders are already {type} for you.'.format(
                  type = 'enabled' if on_or_off else 'disabled'
               ))

            conf['reminders'] = on_or_off
        await ctx.reply('{type} Vote Reminders for you.'.format(type = 'Enabled' if on_or_off else 'Disabled'))

    @_vote_reminder.command(name = 'role')
    @commands.admin_or_permissions(manage_guild = True)
    async def _vote_reminder_role(self, ctx: commands.Context, role: discord.Role):
        await self.config.guild(ctx.guild).vote.role.set(role.id)
        await ctx.reply(
            f'Set Voter Role to {role.name}.'
        )

    @commands.command(name = 'embedpeek', usage = '[message_id] [channel] [start_field]')
    @commands.mod_or_permissions(manage_messages = True)
    async def _embedpeek(self, ctx: commands.Context, message_id: Optional[int], channel: Optional[Union[discord.TextChannel, discord.VoiceChannel]], start_field: Literal['author', 'title', 'description', 'fields', 'footer'] = 'description'):
        """Displays a messages embeds content.
        
        This only shows you the first embed in the message, You can also reply to the message you want to check.
        """
        try:
           message = ctx.message.reference.resolved if ctx.message.reference else await (channel or ctx.channel).fetch_message(message_id)
        except Exception:
           return await ctx.send_help()
        
        if not message.embeds:
           return await ctx.reply('That message has no embeds.')

        embed = message.embeds[0].to_dict()
        view = EmbedPeekView(ctx, embed)  
        return await ctx.send(
            content = await view._format(start_field),
            view = view
        )