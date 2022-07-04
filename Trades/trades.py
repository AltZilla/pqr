import discord

from redbot.core import commands, Config
from .reminder import Reminder
from . import TRADES_GUILD_ID

class Trades(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier = 719180744311701505)
        self.config.register_guild(
            vote__role = None,
            vote__channel = None
        )
        self.config.register_member(
            vote__reminders = True
        )
        self._reminder = Reminder(self, interval = 60)

    async def cog_check(self, ctx: commands.Context) -> bool:
        return ctx.guild.id == TRADES_GUILD_ID

    @commands.Cog.listener('on_member_update')
    async def _vote_reminder_event(self, before: discord.Member, after: discord.Member):
        if after.guild.id != TRADES_GUILD_ID or before.roles == after.roles:
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
          - `on_or_off`: Whether you want to be reminded to vote or not. 
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

    @_vote_reminder.command(name = 'channel')
    @commands.admin_or_permissions(manage_guild = True)
    async def _vote_reminder_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        await self.config.guild(ctx.guild).vote.channel.set(channel.id)
        await ctx.reply(
            f'Set Reminder Channel to {channel.name}.'
        )