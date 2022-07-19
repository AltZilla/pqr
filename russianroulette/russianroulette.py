# Standard Library
import asyncio
import itertools
import random
import time
import typing
import discord
import contextlib

# Russian Roulette
from .kill import outputs

# Red
from redbot.core import Config, bank, checks, commands
from redbot.core.errors import BalanceTooHigh


__version__ = "3.1.07"
__author__ = "Redjumpman"


class RussianRoulette(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, 5074395004, force_registration=True)
        default_guild = {
            "cost": 0,
            "chamber_size": 12,
            "wait_time": 60,
            "emoji": "🩸"
        }
        self.config.register_guild(**default_guild)
        self.cache = {}

    async def red_delete_data_for_user(self, **kwargs):
        """Nothing to delete."""
        return

    @commands.guild_only()
    @commands.command()
    async def russian(self, ctx):
        """Start or join a game of russian roulette.

        The game will not start if no players have joined. That's just
        suicide.

        The maximum number of players in a circle is determined by the
        size of the chamber. For example, a chamber size of 6 means the
        maximum number of players will be 6.
        """
        settings = await self.config.guild(ctx.guild).all()
        await self._check_and_add(ctx, settings)
        session = self.cache[ctx.channel.id]

        if not session['waiting']:
            session['waiting'] = True
            message = await ctx.send(
                "{0.author.mention} is gathering players for a game of russian "
                "roulette!\nReact with {1} to enter! "
                "The round will start <t:{2}:R> or when max players are reached.".format(ctx, settings['emoji'], int(time.time() + settings['wait_time']))
            )
            await message.add_reaction(settings['emoji'])

            async def collect_players():
                while len(self.cache[ctx.channel.id]['players']) < settings['chamber_size']:
                    reaction, user = await self.bot.wait_for('reaction_add', check = lambda r, u: r.message.id == message.id and r.emoji == settings['emoji'] and not u.bot)
                    await self._check_and_add(ctx, settings, user)
            task = asyncio.create_task(
                collect_players()
            )
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(task, timeout = settings['wait_time'])
                await ctx.send('Max players reached... starting.')

            await self.start_game(ctx)


    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @commands.command(hidden=True)
    async def rusreset(self, ctx, channel: typing.Optional[discord.TextChannel]):
        """ONLY USE THIS FOR DEBUGGING PURPOSES"""
        channel = channel or ctx.channel
        with contextlib.suppress(KeyError):
           del self.cache[channel.id]
        await ctx.send(f"The Russian Roulette session for {channel.mention} has been cleared.")

    @commands.group(autohelp=True)
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def setrussian(self, ctx):
        """Russian Roulette Settings group."""
        pass

    @setrussian.command()
    async def chamber(self, ctx, size: int):
        """Sets the chamber size of the gun used. MAX: 12."""
        if not 1 < size <= 12:
            return await ctx.send("Invalid chamber size. Must be in the range of 2 - 12.")
        await self.config.guild(ctx.guild).chamber_size.set(size)
        await ctx.send("Chamber size set to {}.".format(size))

    @setrussian.command()
    async def cost(self, ctx, amount: int):
        """Sets the required cost to play."""
        if amount < 0:
            return await ctx.send("You are an idiot.")
        await self.config.guild(ctx.guild).cost.set(amount)
        currency = await bank.get_currency_name(ctx.guild)
        await ctx.send("Required cost to play set to {} {}.".format(amount, currency))

    @setrussian.command()
    async def wait(self, ctx, seconds: int):
        """Set the wait time (seconds) before starting the game."""
        if seconds <= 0:
            return await ctx.send("You are an idiot.")
        await self.config.guild(ctx.guild).wait_time.set(seconds)
        await ctx.send("The time before a roulette game starts is now {} seconds.".format(seconds))

    async def _check_and_add(self, ctx, settings, author = None):
        user = author or ctx.author
        session = self.cache.setdefault(ctx.channel.id, {'pot': settings['cost'], 'players': [], 'active': False, 'waiting': False})

        if session["active"]:
            with contextlib.suppress(discord.Forbidden):
                return await user.send("You cannot join or start a game of russian roulette while one is active.") 

        elif user.id in session["players"]:
            return await ctx.send("You are already in the roulette circle.") if not author else None

        elif len(session["players"]) >= settings["chamber_size"]:
            return await ctx.send("The roulette circle is full. Wait for this game to finish to join.") if not author else None

        try:
            await bank.withdraw_credits(user, settings["cost"])
        except ValueError:
            currency = await bank.get_currency_name(ctx.guild)
            with contextlib.suppress(discord.Forbidden):
               await user.send("Insufficient funds! This game requires {} {}.".format(settings["cost"], currency)) if not author else None
            return

        self.cache[ctx.channel.id]['pot'] += settings['cost']
        self.cache[ctx.channel.id]['players'].append(user.id)

        if len(session['players']) > 1:
           await ctx.send('{0}, was added to the roulette circle.'.format(user.mention))

    async def start_game(self, ctx):
        session = self.cache.get(ctx.channel.id)
        session['active'] = True
        players = [ctx.guild.get_member(player) for player in session["players"]]
        filtered_players = [player for player in players if isinstance(player, discord.Member)]
        if len(filtered_players) < 2:
            try:
                await bank.deposit_credits(ctx.author, session["pot"])
            except BalanceTooHigh as e:
                await bank.set_balance(ctx.author, e.max_balance)
            await self.reset_game(ctx)
            return await ctx.send("You can't play by youself. That's just suicide.\nGame reset and cost refunded.")
        chamber = await self.config.guild(ctx.guild).chamber_size()

        counter = 1
        while len(filtered_players) > 1:
            await ctx.send(
                "**Round {}**\n*{} spins the cylinder of the gun "
                "and with a flick of the wrist it locks into "
                "place.*".format(counter, ctx.bot.user.name)
            )
            await asyncio.sleep(3)
            await self.start_round(ctx, chamber, filtered_players)
            counter += 1
        await self.game_teardown(ctx, filtered_players)

    async def start_round(self, ctx, chamber, players):
        position = random.randint(1, random.randint(len(players), chamber))
        while True:
            for turn, player in enumerate(itertools.cycle(players), 1):
                await ctx.send(
                    "{} presses the revolver to their head and slowly squeezes the trigger...".format(player.name)
                )
                await asyncio.sleep(5)
                if turn == position:
                    players.remove(player)
                    msg = "**BANG!** {0} is now dead.\n"
                    msg += random.choice(outputs)
                    await ctx.send(msg.format(player.mention, random.choice(players).name, ctx.guild.owner))
                    await asyncio.sleep(3)
                    break
                else:
                    await ctx.send("**CLICK!** {} passes the gun along.".format(player.name))
                    await asyncio.sleep(3)
            break

    async def game_teardown(self, ctx, players):
        winner = players[0]
        currency = await bank.get_currency_name(ctx.guild)
        total = self.cache[ctx.channel.id]['pot']
        try:
            await bank.deposit_credits(winner, total)
        except BalanceTooHigh as e:
            await bank.set_balance(winner, e.max_balance)
        await ctx.send(
            "Congratulations {}! You are the last person standing and have "
            "won a total of {} {}.".format(winner.mention, total, currency)
        )
        await self.reset_game(ctx)

    async def reset_game(self, ctx):
        with contextlib.suppress(KeyError):
           del self.cache[ctx.channel.id]