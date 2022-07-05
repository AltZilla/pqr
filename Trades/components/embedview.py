import discord

from redbot.core import commands

class EmbedDropdown(discord.ui.Select):
    async def callback(self, interaction: discord.Interaction):
        _format = await self.view._format(self.values[0])
        await interaction.response.defer()
        return await interaction.message.edit(
            content = _format
        )

class EmbedPeekView(discord.ui.View):
    def __init__(self, ctx: commands.Context, embed_raw: dict):
        super().__init__(timeout = None)
        self._ctx = ctx
        self._embed = embed_raw

        self.add_item(
            EmbedDropdown(placeholder = 'Select Field', options = [discord.SelectOption(label = label, value = label.lower()) for label in ['Author', 'Title', 'Description', 'Fields', 'Footer']])
        )

    async def _format(self, name: str):
        response = self._embed.get(name)
        if isinstance(response, str):
           return f'**{name.capitalize()}:** {response}'
        elif isinstance(response, dict):
           return '\n\n'.join([f'**{key.capitalize()}:** {value}' for key, value in response.items()])
        elif isinstance(response, list):
           return 'Still have to do this, shutup.'

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self._ctx.author:
           await interaction.response.send_message(
              'This menu is not for you.', ephemeral = True
           )
           return False
        return True