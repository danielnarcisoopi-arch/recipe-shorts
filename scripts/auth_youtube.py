"""One-time local OAuth. Use a dedicated recipe-channel token; never commit it."""
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from recipe_shorts.youtube import authenticated_channel

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
CLIENT = Path("client_secret.json")
TOKEN = Path("token-recipes.json")

if not CLIENT.exists():
    raise SystemExit("Guarde o OAuth Client JSON do Google Cloud como client_secret.json")
flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent", login_hint="")
TOKEN.write_text(credentials.to_json(), encoding="utf-8")
channel_id, name = authenticated_channel(TOKEN.read_text(encoding="utf-8"))
print(f"Canal autorizado: {name} (ID: {channel_id})")
print("Use este ID como EXPECTED_YOUTUBE_CHANNEL_ID e o conteúdo de token-recipes.json como YOUTUBE_TOKEN_JSON no repositório de receitas.")
print("Não altere o segredo nem o token do projeto CS2.")
