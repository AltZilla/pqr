import discord
import re

from redbot.core.utils.chat_formatting import humanize_list
from typing import List

class Matches:
    def __init__(self):
        self._matches = []

    def __len__(self):
        return self._matches.__len__()

    def __contains__(self, con: str):
        for item in self._matches:
            if item['highlight'].strip() == con.strip():
               return True
        return False

    def add_match(self, match: re.Match, highlight_data: dict):
        if not any(h['highlight'] == highlight_data['highlight'] for h in self._matches):
           highlight_data['match'] = match.group(0)
           self._matches.append(highlight_data)

    def remove_match(self, match: re.Match, Highlight_data: dict):
        for item in self._matches:
            if item['match'] == match.group(0) and item['highlight'] == Highlight_data['highlight']:
               self.matches.remove(item)

    def format_response(self):
        response = []
        for item in self._matches:
            conversions = {
                'default': lambda: f'\"{item["match"]}\"',
                'wildcard': lambda: f'\"{item["match"]}\"' if item['match'].strip().lower() == item['highlight'].strip().lower() else f'\"{item["match"]}\" from wildcard `({item["highlight"]})`',
                'regex': lambda: f'\"{item["match"]}\" from regex `({item["highlight"]})`'
            }
            response.append(conversions.get(item['type'])())
        return humanize_list(response)

    def format_title(self):
        matches = [item['match'].strip() for item in self._matches]

        if len(matches) < 3:
           title = ', '.join(matches)
        else:
           title = ', '.join(matches[:2]) + f' + {len(matches) - 2} more.'

        if len(title) > 50:
           title = title[:47] + '...'
        return title
    
class HighlightView(discord.ui.View):
   def __init__(self, message: discord.Message, highlights: list, positions: List[int] = None):
       super().__init__(timeout = None)
       self.message = message
       self.content = message.content
       self.attachments = message.attachments
       self.embeds = message.embeds
       self.highlights = highlights
       self.data = {}

       if len(self.content) > 500 or self.attachments or self.embeds:

          button = discord.ui.Button(
             label = 'View Message',
             style = discord.ButtonStyle.secondary
          )
          button.callback = self.execute
          self.add_item(button)

       else:
          button = discord.ui.Button(
             label = 'Jump To Source',
             style = discord.ButtonStyle.link,
             url = self.message.jump_url
          )
          self.add_item(button)

   async def execute(self, interaction: discord.Interaction):
       
       for highlight in self.highlights:
           regex = re.compile(rf'\b{re.escape(highlight)}\b', flags = re.IGNORECASE)
           replace_re = r'**__\g<0>__**'
           content = regex.sub(replace_re, self.content)

           for embed in self.embeds:
               embed.description = regex.sub(replace_re, embed.description)[:2000] if embed.description else None
               fields = []
               for field in embed.fields:
                   value = field.value = regex.sub(replace_re, field.value) if field.value else None
                   fields.append({'name': field.name, 'value': value})
               embed.clear_fields()
               [embed.add_field(**field) for field in fields]
            
       data = {
             'content': content,
             'embeds': self.embeds,
             'files': [await attach.to_file() for attach in self.attachments],
             'view': discord.ui.View.from_message(self.message),
             'ephemeral': True
       }

       await interaction.response.send_message(**data)

       self.clear_items()
       button = discord.ui.Button(
            label = 'Jump To Source',
            style = discord.ButtonStyle.link,
            url = self.message.jump_url
       )
       self.add_item(button)
       await interaction.message.edit(view = self)