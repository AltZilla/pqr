import discord
from typing import List, Tuple, Union

class PossibleSelect(discord.ui.Select):
    def __init__(self, **data: List[Tuple[Union[discord.Member, discord.Role, discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel]]]):
        self._data = data

        super().__init__(
            placeholder = 'Select Type...',
            options = [
                discord.SelectOption(label = key.capitalize() + f' ({len(value)})', value = key) 
                for key, value in data.items()
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        _requested = self.values[0]
        data = self._data.get(_requested, [])

        avg_score = sum(map(lambda d: d[1], data)) / len(data)
        response = [f'> {_requested.capitalize()}: (Average Score -> {avg_score})\n']
        for i, obj in enumerate(data, 1):
            response.append((f'{i}. {obj[0].mention} - ({obj[0].id}) - (score -> {obj[1]})'))

        await interaction.response.edit_message(content = '\n'.join(response))

class PossibleMentionsView(discord.ui.View):
    def __init__(self, user, **data):
        self.user = user
        self.data = data
        super().__init__(timeout = None)
        self.add_item(PossibleSelect(**data))

    async def start(self, interaction: discord.Interaction):
        data = self.data.get('members', [])
        avg_score = sum(map(lambda d: d[1], data)) / len(data)

        response = [f'> Members: (Average Score -> {avg_score})\n']
        for i, obj in enumerate(data, 1):
            response.append((f'{i}. {obj[0].mention} - ({obj[0].id}) - (score -> {obj[1]})'))

        await interaction.followup.send('\n'.join(response), view = self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user == self.user

    
   
    
