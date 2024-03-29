import discord

from . import TRADES_GUILD_ID
from redbot.core import commands, Config
from typing import Literal, Optional, Tuple, Union, List
from .reminder import Reminder
from .components import EmbedPeekView

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
        self.dank_item_list = [
            "A plus",
            "Adventure Ticket",
            "Adventure Voucher",
            "Aetheryx' Flower",
            "Aiphey's Gemstone",
            "Alcohol",
            "Alexa's Megaphone",
            "Alien Sample",
            "Amathine's Butterfly",
            "Ammo",
            "Ant",
            "Anti-Rob Pack",
            "Apple",
            "Armpit Hair",
            "Baby",
            "Badosz's Card",
            "Ban Hammer",
            "Bank Note",
            "Barrel of Sludge",
            "Beaker of sus fluid",
            "Bean",
            "Bean Mp3 Player",
            "Berries and Cream",
            "Binary",
            "Black Hole",
            "Blob",
            "Blue Plastic Bits",
            "Blue's Plane",
            "Boar",
            "Bolt Cutters",
            "Bottle of Whiskey",
            "Box Box",
            "Box of Sand",
            "Boxed Chocolates",
            "Bundle Box",
            "Bunny's Apron",
            "Cactus",
            "Camera",
            "Candy",
            "Candy Cane",
            "Cell Phone",
            "Chill Pill",
            "Chocolate Cake",
            "Christmas Tree",
            "Coin Bomb",
            "Common Fish",
            "Cookie",
            "Corncob",
            "Corndog",
            "Cowboy Boots",
            "Cowboy Hat",
            "Credit Card",
            "Crunchy Taco",
            "Cupid's Big Toe",
            "Cursed Pepe",
            "Daily Box",
            "Dank Box",
            "Deer",
            "Developer Box",
            "Dragon",
            "Duck",
            "Duct Tape",
            "Ectoplasm",
            "Empowered Fart Bottle",
            "Enchanted Badosz's Card",
            "Energy Drink",
            "Engagement Ring",
            "Exotic Fish",
            "Fake ID",
            "Fart In A Bottle",
            "Fidget Spinner",
            "Fishing Bait",
            "Fishing Pole",
            "Fool's Notif",
            "Fossil",
            "Fresh Bread",
            "Friend's Gift",
            "Garbage",
            "Gift Box",
            "God Box",
            "Golden Corndog",
            "Golden Nugget",
            "Golden Plastic Bits",
            "Green Screen",
            "Grind Pack",
            "Headphones",
            "Holiday Stocking",
            "Holy Badosz's Bread",
            "Holy Water",
            "Hunting Rifle",
            "Jacky o' Lanty",
            "Jar Of Singularity",
            "Jelly Fish",
            "Junk",
            "Kable's Sunglasses",
            "Keyboard",
            "Kraken",
            "Ladybug",
            "Landmine",
            "Laptop",
            "Lasso",
            "Law Degree",
            "Legendary Fish",
            "Life Saver",
            "Like Button",
            "Literally Karen",
            "Literally a Tree",
            "Lucky Horseshoe",
            "Melmsie's Beard",
            "Meme Box",
            "Meme pills",
            "Meteorite",
            "Microphone",
            "Motivational Poster",
            "Mouse",
            "Multi Colored Plastic Bits",
            "Musical Note",
            "New Player Pack",
            "Normie Box",
            "Odd Eye",
            "Old Box",
            "Old Cowboy Revolver",
            "Orange Plastic Bits",
            "Ornament",
            "Out West Adventure Box",
            "Padlock",
            "Patreon Box",
            "Patreon Pack",
            "Pepe Box",
            "Pepe Coin",
            "Pepe Crown",
            "Pepe Medal",
            "Pepe Ribbon",
            "Pepe Ring",
            "Pepe Statue",
            "Pepe Sus",
            "Pepe Trophy",
            "Pet Collar",
            "Pet Saddle",
            "Pink Plastic Bits",
            "Pizza Slice",
            "Plastic Box",
            "Police Badge",
            "Potato",
            "Prestige Coin",
            "Prestige Pack",
            "Purple Plastic Bits",
            "Rabbit",
            "Rare Fish",
            "Rare Pepe",
            "Reversal Card",
            "Ring Light",
            "Robbers Mask",
            "Robbers Wishlist",
            "Royal Scepter",
            "Sanic Hot Dog",
            "Santa's Bag",
            "Santa's Hat",
            "School Urinal",
            "Seaweed",
            "Shooting Star",
            "Shop Coupon",
            "Shovel",
            "Shredded Cheese",
            "Skunk",
            "Snowball",
            "Snowflake",
            "Sound Card",
            "Space Adventure Box",
            "Spider",
            "Stack of Cash",
            "Star Fragment",
            "Stickbug",
            "Stonk Machine",
            "Streak Freeze",
            "Sugar Skull",
            "The Letter",
            "Tidepod",
            "Tip Jar",
            "Toilet Paper",
            "Townie's Eyes",
            "Trash",
            "Treasure Map",
            "Tumbleweed",
            "Used Diaper",
            "Vaccine",
            "Wedding Gift",
            "Winning Lottery Ticket",
            "Work Box",
            "Worm",
            "Yeng's Paw",
            "Zig's Capybara"
        ]

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