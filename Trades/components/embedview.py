import discord

from redbot.core import commands
from redbot.core.utils.chat_formatting import pagify

class Menu(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, pages):
        self._interaction = interaction
        self._pages = pages
        self._current_page = 0
        super().__init__()

    async def edit(self, meta: discord.ui.View):
        if len(self._pages) > 1:
           for item in self.children:
               meta.add_item(item)
        else:
           meta.clear_items()
           meta.add_item(meta.drop)
        await self._interaction.message.edit(self._pages[self._current_page], view = meta)
        self.stop()

    async def update(self, inter):
        if self._current_page + 1 > len(self._pages):
            self._current_page = 0
        elif self._current_page == 0:
            self._current_page = len(self._pages) - 1

        page = self._pages[self._current_page]
        await inter.message.edit(page)
        await inter.response.defer()

    @discord.ui.button(emoji = "\N{LEFTWARDS BLACK ARROW}\N{VARIATION SELECTOR-16}", custom_id = 'prev')
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._current_page -= 1
        await self.update(interaction)

    @discord.ui.button(emoji = "\N{BLACK RIGHTWARDS ARROW}\N{VARIATION SELECTOR-16}", custom_id = 'next')
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._current_page += 1
        await self.update(interaction)

class EmbedDropdown(discord.ui.Select):
    async def callback(self, interaction: discord.Interaction):
        _format = await self.view._format(self.values[0])
        await interaction.response.defer()
        await Menu(interaction, [page for page in pagify(_format, delims = ["\n\n"])]).edit(meta = self.view)

class EmbedPeekView(discord.ui.View):
    def __init__(self, ctx: commands.Context, embed_raw: dict):
        super().__init__(timeout = None)
        self._ctx = ctx
        self._embed = embed_raw

        self.drop = EmbedDropdown(placeholder = 'Select Field', options = [discord.SelectOption(label = label, value = label.lower()) for label in ['Author', 'Title', 'Description', 'Fields', 'Footer']])
        self.add_item(self.drop)

    async def _format(self, name: str):
        response = self._embed.get(name)
        if isinstance(response, str):
           return f'**{name.capitalize()}:** {response}'
        elif isinstance(response, dict):
           return '\n\n'.join([f'**{key.capitalize()}:** {value}' for key, value in response.items()])
        elif isinstance(response, list):
           formatted = []
           for i, field in enumerate(response, 1):
               header = f'--------------Field {i}--------------\n\n'
               formatted.append(
                  header + '\n'.join([f'**{key.capitalize()}:** {value}' for key, value in reversed(field.items()) if key not in ['inline']])
               )
           return '\n\n'.join(formatted)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self._ctx.author:
           await interaction.response.send_message(
              'This menu is not for you.', ephemeral = True
           )
           return False
        return True