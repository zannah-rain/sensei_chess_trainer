"""A package that helps connect to lichess"""

import os

import berserk

# A personal API token from https://lichess.org/account/oauth/token - needed to
# download your own games and query rate-limited endpoints. Left unset, requests
# that need authentication will fail at call time (not at import time), so the
# rest of the app still works without one.
api_key = os.environ.get("LICHESS_API_KEY")
session = berserk.TokenSession(api_key) if api_key else None
client = berserk.Client(session=session)
