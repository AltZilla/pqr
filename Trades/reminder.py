import discord
import asyncio
import time
import logging

from redbot.core import commands
from redbot.core.utils.chat_formatting import humanize_list

log = logging.getLogger('red.cogs.Trades')

class RemindView(discord.ui.View):
    def __init__(self, config):
        self._config = config
        super().__init__(timeout = None)

    @discord.ui.button(label = 'Toggle Reminders', style = discord.ButtonStyle.primary)
    async def _toggle_reminders(self, interaction: discord.Interaction, button: discord.Button):
        async with self._config.member(interaction.user).vote() as conf:
            _toggle = True if conf['reminders'] == False else False
            conf['reminders'] = _toggle

        return await interaction.response.send_message(
            '{type} Vote Reminders for you.'.format(type = 'Enabled' if _toggle else 'Disabled'),
            ephemeral = True
        )


class Reminder:
    def __init__(self, cog: commands.Cog, interval: int = 60):
        self._cog = cog
        self._interval = interval
        self._last_sent_at = time.time() - interval

        self._task = asyncio.create_task(self._reminder_task())
        self._queue = asyncio.Queue()

    def remind(self, member: discord.Member):
        self._queue.put_nowait(member)

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

                async with self._cog.config.guild_from_id(719180744311701505).vote() as vote:
                    channel = self._cog.bot.get_channel(vote['channel'])
                    if channel:
                        response = f'Hello, {humanize_list([m.mention for m in set(pending_members)])}!'
                        embed = discord.Embed(
                           title = 'Vote Reminder',
                           description = "You can vote for us at the following links: \nTop.gg : https://top.gg/servers/719180744311701505/vote\nDiscord Bot List: https://discordbotlist.com/servers/trades/upvote\n\n**Perks For Voting**\n- Access to <#831648667483635763> and <#760952492715802664>; a channel where you can grind with less people and gain **DOUBLE XP**.\n- Hoisted Role, the <@&759101400012685433> is quite high on the role hierarchy and you will show up on the sidebar.\n- You help us grow, which allows us to hold larger heists, giveaways, and other events",
                           colour = await self._cog.bot.get_embed_colour(location = channel)
                        ).set_footer(
                           text = 'Click the button below or run `p?votereminder` to toggle reminders.',
                           icon_url = channel.guild.icon.url
                        ).set_thumbnail(url = channel.guild.icon.url)
                        await channel.send(
                            response, 
                            embed = embed, 
                            view = RemindView(self._cog.config)
                        )
            except Exception as e:
                log.error('Failed to send reminder.', exc_info = e)