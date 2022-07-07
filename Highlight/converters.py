import discord
import argparse
import re

from fuzzywuzzy import process
from redbot.core import commands


class FuzzyChannels(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str):
        try:
            return await commands.GuildChannelConverter().convert(ctx, argument)
        except Exception:
            channel, acc = process.extractOne(argument, [channel.name for channel in ctx.guild.channels])
            if acc < 60:
                raise commands.ChannelNotFound(argument)
            channel = discord.utils.get(ctx.guild.channels, name = channel)
            if not isinstance(channel, discord.TextChannel) or not isinstance(channel, discord.VoiceChannel):
               raise commands.BadArgument('The channel should be a Text channel or Voice channel.')
            return channel

class TimeConverter(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str):
       matches = re.findall(r'([0-9]+) *([a-zA-Z]+)', argument)
       seconds = 0
       for match in matches:
           if match[1].startswith("s"):
              seconds  += int(match[0])
           elif match[1].startswith("m"):
              seconds  += (int(match[0]) * 60)
           elif match[1].startswith("h"):
              seconds  += (int(match[0]) * 3600)
           elif match[1].startswith("d"):
              seconds  += (int(match[0]) * 86400)
           elif match[1].startswith("w"):
              seconds  += (int(match[0]) * 604800)
           elif match[1].startswith("y"):
              seconds  += (int(match[0]) * 31536000)
           else:
              seconds += int(match[0])
       return seconds
        

class NoExitParser(argparse.ArgumentParser):
    def error(self, message):
        raise commands.BadArgument(message)

class HighlightFlagResolver(commands.Converter):
    async def convert(self, ctx: commands.Context, argument):
        parser = NoExitParser(description = "Highlight flag resolver")

        parser.add_argument('words', nargs = '+', help = "Words to highlight")
        parser.add_argument('--multiple', '-m', dest = 'multiple', action = 'store_true')
        parser.add_argument('--channel', '-c', dest = 'channel', type = str, nargs = '*', default = None, required = False)
        # types
        parser.add_argument('--regex', '-r', dest = 'regex', action = 'store_true')
        parser.add_argument('--wildcard', '-w', dest = 'wildcard', action = 'store_true')
        # settings
        parser.add_argument('--set', '-s', dest = 'settings', type = str, nargs = '+', default = [], required = False)

        args = vars(parser.parse_args(argument.split()))

        if args['channel']:
           channel = await FuzzyChannels().convert(ctx, ' '.join(args['channel']))
           args['channel'] = channel if channel else None

        elif (not args['channel']) and any(f in argument for f in ['--channel', '-c']):
           args['channel'] = ctx.channel

        if args['multiple'] == False:
           args['words'] = [' '.join(args['words'])]

        if args['settings']:
           for setting in args['settings']:
               if not setting.lower() in ['bots', 'embeds', 'images']:
                  args['settings'].remove(set)

           if not args['settings']:
               raise commands.BadArgument('Invalid Setting Type.')

        args['words'] = list(set(map(lambda w: w.strip().lower(), args['words'])))
        
        args['type'] = 'regex' if args['regex'] else 'wildcard' if args['wildcard'] else 'default'
        return args