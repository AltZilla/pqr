import discord
import argparse
import re

from redbot.core import commands
        
class NoExitParser(argparse.ArgumentParser):
    def error(self, message):
        raise commands.BadArgument(message)

class HighlightFlagResolver(commands.Converter, NoExitParser):

    async def convert(self, ctx: commands.Context, argument):
        parser = NoExitParser(description = "Highlight flag resolver")

        parser.add_argument('words', nargs = '+', help = "Words to highlight")
        parser.add_argument('--multiple', '-m', dest = 'multiple', action = 'store_true')
        # types
        parser.add_argument('--regex', '-r', dest = 'regex', action = 'store_true')
        parser.add_argument('--wildcard', '-w', dest = 'wildcard', action = 'store_true')
        # settings
        parser.add_argument('--set', '-s', dest = 'settings', type = str, nargs = '+', default = [], required = False)

        args = vars(parser.parse_args(argument.split()))

        if args['multiple'] == False:
           args['words'] = [' '.join(args['words'])]

        if args['settings']:
           for setting in args['settings']:
               if not setting in ['bots', 'embeds', 'images']:
                  await ctx.send_help()
                  raise commands.BadArgument(f'Invalid Setting \"{setting}\", read the help embed again ^^')

        # one two three -m
        e = map(lambda w: w.strip().lower(), args['words'])
        args['words'] = list(set(e))
        
        args['type'] = 'regex' if args['regex'] else 'wildcard' if args['wildcard'] else 'default'
        return args