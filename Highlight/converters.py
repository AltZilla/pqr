import discord
import argparse

from fuzzywuzzy import process
from redbot.core.commands import BadArgument, Converter, Context, GuildChannelConverter, ChannelNotFound


class FuzzyChannels(Converter):
    async def convert(self, ctx: Context, argument: str):
        try:
            return await GuildChannelConverter().convert(ctx, argument)
        except Exception:
            channel, acc = process.extractOne(argument, [channel.name for channel in ctx.guild.channels])
            if acc < 60:
                raise ChannelNotFound(argument)
            channel = discord.utils.get(ctx.guild.channels, name = channel)
            if isinstance(channel, discord.CategoryChannel):
               raise BadArgument('The channel should be a Text channel or Voice channel, not a category.')
            return channel
        

class NoExitParser(argparse.ArgumentParser):
    def error(self, message):
        raise BadArgument(message)

class HighlightFlagResolver(Converter):
    async def convert(self, ctx: Context, argument):
        parser = NoExitParser(description = "Highlight flag resolver")

        parser.add_argument('words', nargs = '+', help = "Words to highlight")
        parser.add_argument('--multiple', '-m', dest = 'multiple', action = 'store_true')
        parser.add_argument('--channel', '-c', dest = 'channel', type = str, nargs = '*', default = None, required = False)
        # types
        parser.add_argument('--regex', '-r', dest = 'regex', action = 'store_true')
        parser.add_argument('--wildcard', '-w', dest = 'wildcard', action = 'store_true')
        # settings
        parser.add_argument('--bots', '-b', dest = 'bots', action = 'store_true')
        parser.add_argument('--images', '-i', dest = 'images', action = 'store_true')

        args = vars(parser.parse_args(argument.split()))

        if args['channel']:
           channel = await FuzzyChannels().convert(ctx, ' '.join(args['channel']))
           args['channel'] = channel if channel else None

        elif (not args['channel']) and any(f in argument for f in ['--channel', '-c']):
           args['channel'] = ctx.channel

        if args['multiple'] == False:
           args['words'] = [' '.join(args['words'])]

        settings = [s for s in [args['bots'], args['images']] if s]
        if len(settings) > 1:
           raise BadArgument("You can only use one of the following flags: `bots`, `images`.")

        args['setting'] = 'bots' if args['bots'] else 'images' if args['images'] else None

        args['words'] = list(set(map(lambda w: w.strip().lower(), args['words'])))
        
        args['type'] = 'regex' if args['regex'] else 'wildcard' if args['wildcard'] else 'default'
        return args