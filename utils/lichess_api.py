"""A package that helps connect to lichess"""

import berserk

api_key = "REDACTED_LICHESS_API_KEY"
session = berserk.TokenSession(api_key)
client = berserk.Client(session=session)

