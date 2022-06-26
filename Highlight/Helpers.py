import asyncio
import discord
import contextlib
import aiohttp
import re

from discord.ext import tasks
from redbot.core import commands
from typing import (
    List,
    Optional
)

class Queue(asyncio.Queue):
    def __init__(self, maxsize = 0):
        super().__init__(maxsize = maxsize)

    @tasks.loop(seconds = 3)
    async def dm_task(self):
        if not self.empty():
           member, response = await self.get()
           with contextlib.suppress(discord.Forbidden):
              await member.send(**response)
        else:
           self.dm_task.cancel()


    async def put(self, item):
        await super().put(item)
        if not self.dm_task.is_running():
           self.dm_task.start()

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

class OCRSpace:
    def __init__(
        self,
        endpoint='https://api.ocr.space/parse/image',
        api_key='K85512258788957',
        language='eng',
        **kwargs,
    ):
        self.endpoint = endpoint
        self.payload = {
            'isOverlayRequired': True,
            'apikey': api_key,
            'language': language,
            **kwargs
        }

    async def _parse(self, raw):
        if type(raw) == str:
            raise Exception(raw)
        if raw['IsErroredOnProcessing']:
            raise Exception(raw['ErrorMessage'][0])
        return raw['ParsedResults'][0]['ParsedText']

    async def ocr_url(self, url):
        data = self.payload
        data['url'] = url

        async with aiohttp.ClientSession() as client:
            async with client.request(
               method = 'POST',
               url = self.endpoint,
               data = data,
           ) as resp:
               raw = await resp.json()
        return await self._parse(raw)