"""A package that helps connect to lichess"""

import berserk

api_key = "lip_NOjl7oFbm9wcnfsfX3hw"
session = berserk.TokenSession(api_key)
client = berserk.Client(session=session)

