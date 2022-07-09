import discord
import aiohttp
import asyncio
import io
import re

from copy import copy
from typing import List
from redbot.core.utils.chat_formatting import humanize_list
from stemming.porter2 import stem

try:
   import pytesseract
   from PIL import Image
except ImportError:
   pytesseract = False

IMAGE_REGEX = re.compile(
    r'(?:(?:https?):\/\/)?[\w\/\-?=%.]+\.(?:png|jpg|jpeg)+', flags = re.I
)

class MessageRaw:
    def __init__(self, message: discord.Message, bots: str, images: str):
        self._message = message
        self._bots = bots
        self._images = images

    def string_from_config(self, default_conf: dict, highlight_conf: dict):
        content, settings = (
           copy(self._message.content if not self._message.author.bot else ''),
           highlight_conf.get('settings', [])
        )

        if (default_conf.get('bots') or 'bots' in settings) and self._message.author.bot:
           content += self._message.content + ' ' + self._bots

        if default_conf.get('images') or 'images' in settings:
           content += ' ' + self._images

        return content
        
    @classmethod
    async def from_message(cls, message: discord.Message):
         message_raw = {
            'message': message,
            'bots': '',
            'images': ''
         }

         if message.embeds:
            texts = []
            for embed in message.embeds:
                for key, value in embed.to_dict().items():
                    if key in ['type', 'color']:
                       continue
                    if isinstance(value, dict):
                       for k, v in value.items():
                           if isinstance(v, str) and not v.startswith('http'): # ignore links
                              texts.append(v)
                    elif isinstance(value, list):
                       texts.extend(field['name'] + ' ' + field['value'] for field in value)
                    else:
                       texts.append(value)

            message_raw['bots'] = ' '.join(texts)

         if pytesseract != False:
            texts = []

            async def image_to_string(attachment: discord.Attachment = None, url: str = None):
               if attachment:
                  temp_ = io.BytesIO(await attachment.read())
               elif url:
                  temp_ = io.BytesIO()
                  async with aiohttp.ClientSession() as session:
                     async with session.get(url) as r:
                        raw = await r.read()
                        temp_.write(raw)
                        temp_.seek(0)
               result = pytesseract.image_to_string(Image.open(temp_), lang = 'eng')
               texts.append(result)
                  
            tasks = []
            for attach in message.attachments:
                tasks.append(image_to_string(attachment = attach))

            for url in IMAGE_REGEX.findall(message.content):
                tasks.append(image_to_string(url = url))

            try:
               await asyncio.wait_for(asyncio.gather(*tasks), timeout = 10)
            except asyncio.TimeoutError:
               pass
            
            message_raw['images'] = ' '.join(texts)
         
         return cls(**message_raw)

class Matches:
    def __init__(self, conf: dict, highlights: dict, message_raw: MessageRaw = None):
        self._matches = []
        self._conf = conf
        self._highlights = highlights
        self._message_raw = message_raw

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

    def remove_match(self, match: str):
        for item in self._matches:
            if item['match'] == match:
               self._matches.remove(item)

    async def resolve(self, message: discord.Message = None):
        if not self._message_raw:
           self._message_raw = await MessageRaw.from_message(message)

        for data in self._highlights:
              s = self._message_raw.string_from_config(default_conf = self._conf, highlight_conf = data)
              stemmed_content = ' '.join(stem(word) for word in s.split())

              type_converter = {
                  'default': lambda: re.compile(rf'\b{re.escape(data["highlight"])}\b', re.IGNORECASE),
                  'regex': lambda: re.compile(data['highlight']),
                  'wildcard': lambda: re.compile(''.join([f'{re.escape(char)}[ _.{re.escape(char)}-]*' for char in data['highlight']]), re.IGNORECASE)
              }
            
              pattern = type_converter.get(data['type'])()
              if match := pattern.search(s):
                  self.add_match(match = match, highlight_data = data)
              elif match := pattern.search(stemmed_content) and data['type'] == 'default':
                  self.add_match(match = match, highlight_data = data)
        return self

    def format_response(self):
        response = []
        for item in self._matches:
            conversions = {
                'default': lambda: f'\"{item["match"]}\"',
                'wildcard': lambda: f'\"{item["match" if len(item["match"]) < 100 else "[EXCEEDED 100 CHAR LIMIT]"]}\"' if item['match'].strip().lower() == item['highlight'].strip().lower() else f'\"{item["match"]}\" from wildcard `({item["highlight"]})`',
                'regex': lambda: f'\"{item["match"] if len(item["match"]) < 100 else "[EXCEEDED 100 CHAR LIMIT]"}\" from regex `({item["highlight"]})`'
            }
            response.append(conversions.get(item['type'])())
        return humanize_list(response[:10])

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