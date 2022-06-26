import re

from redbot.core.utils.chat_formatting import humanize_list

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