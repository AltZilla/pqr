import discord
import asyncio
import time
import logging

from . import TRADES_GUILD_ID
from redbot.core import commands
from redbot.core.utils.chat_formatting import humanize_list

log = logging.getLogger('red.cogs.Trades')

class Reminder:
    def __init__(self, cog: commands.Cog, interval: int = 60):
        self._cog = cog
        self._interval = interval
        self._last_sent_at = time.time() - interval

        self._task = asyncio.create_task(self._reminder_task())
        self._queue = asyncio.Queue()

        self._view = discord.ui.View(timeout = None)
        self._view.add_item(
            discord.ui.Button(label = 'Top.gg', style = discord.ButtonStyle.link, url = 'https://top.gg/servers/719180744311701505/vote')
        )
        self._view.add_item(
            discord.ui.Button(label = 'dbl.com', style = discord.ButtonStyle.link, url = 'https://discordbotlist.com/servers/trades/upvote')
        )
        button = discord.ui.Button(
            label = 'Toggle Reminders',
            emoji = '<:t_yallNeedJesus:934016516037423124>',
            style = discord.ButtonStyle.gray
        )
        button.callback = self._toggle_reminder
        self._view.add_item(button)

    def remind(self, member: discord.Member):
        self._queue.put_nowait(member)

    async def _toggle_reminder(self, interaction: discord.Interaction):
        async with self._cog.config.member(interaction.user).vote() as conf:
            _toggle = True if conf['reminders'] == False else False
            conf['reminders'] = _toggle

        return await interaction.response.send_message(
            '{type} Vote Reminders for you.'.format(type = 'Enabled' if _toggle else 'Disabled'),
            ephemeral = True
        )

    async def _reminder_task(self):
        while True:
            try:
                next_ = await self._queue.get()

                last_send = time.time() - self._last_sent_at
                if last_send < self._interval:
                   await asyncio.sleep(self._interval - last_send)

                self._last_sent_at = time.time()

                pending_members = [next_]
                while self._queue.empty() is False:
                    pending_members.append(self._queue.get_nowait())

                async with self._cog.config.guild_from_id(TRADES_GUILD_ID).vote() as vote:
                    channel = self._cog.bot.get_channel(vote['channel'])
                    if channel:
                        response = f'Hello, {humanize_list([m.mention for m in set(pending_members)])}!'
                        embed = discord.Embed(
                           title = 'Vote Reminder',
                           description = "You can vote for us at the following links: \nTop.gg : https://top.gg/servers/719180744311701505/vote\nDiscord Bot List: https://discordbotlist.com/servers/trades/upvote\n\n> Run `i?vote` for a list of perks.",
                           colour = await self._cog.bot.get_embed_colour(location = channel)
                        ).set_footer(
                           text = 'Click the button below or run `p?votereminder` to toggle reminders.',
                           icon_url = channel.guild.icon.url
                        ).set_thumbnail(url = channel.guild.icon.url)
                        await channel.send(
                            response, 
                            embed = embed, 
                            view = self._view
                        )
            except Exception as e:
                log.error('Failed to send reminder.', exc_info = e)