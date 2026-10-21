from __future__ import annotations

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .media import verify_shorts_format

# Read-only access is used only for the pre-upload channel identity guard.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]


def _credentials(token_json: str):
    try:
        token = json.loads(token_json)
    except json.JSONDecodeError as exc:
        raise ValueError("YOUTUBE_TOKEN_JSON tem de conter o JSON completo de token.json") from exc
    credentials = Credentials.from_authorized_user_info(token, SCOPES)
    if not credentials.valid:
        if not credentials.refresh_token:
            raise RuntimeError("Token OAuth sem refresh_token; execute scripts/auth_youtube.py novamente")
        credentials.refresh(Request())
    return credentials


def authenticated_channel(token_json: str) -> tuple[str, str]:
    credentials = _credentials(token_json)
    service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    response = service.channels().list(part="id,snippet", mine=True, maxResults=50).execute()
    channels = response.get("items", [])
    if len(channels) != 1:
        names = [x.get("snippet", {}).get("title", "(sem nome)") for x in channels]
        raise RuntimeError(f"O OAuth devolveu {len(channels)} canais ({names}); autorize o canal de receitas e confirme que só ele está associado a este token")
    return channels[0]["id"], channels[0].get("snippet", {}).get("title", "")


def upload(video_path: Path, short, token_json: str, expected_channel_id: str,
           privacy: str = "public", notify: bool = False) -> str:
    verify_shorts_format(video_path)
    if not token_json:
        raise RuntimeError("Falta o segredo YOUTUBE_TOKEN_JSON; os uploads estão desativados")
    if not expected_channel_id:
        raise RuntimeError("Defina EXPECTED_YOUTUBE_CHANNEL_ID no repositório de receitas; sem ele, o upload não começa")
    channel_id, _ = authenticated_channel(token_json)
    if channel_id != expected_channel_id:
        raise RuntimeError(f"Proteção de canal: o token aponta para {channel_id}, mas este workflow está configurado para {expected_channel_id}; nenhum vídeo foi enviado")
    credentials = _credentials(token_json)
    service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    body = {"snippet": {"title": short.title, "description": short.description,
                         "tags": short.tags, "categoryId": "26", "defaultLanguage": "pt"},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
    request = service.videos().insert(part="snippet,status", body=body, notifySubscribers=notify,
        media_body=MediaFileUpload(str(video_path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True))
    response = None
    while response is None:
        _, response = request.next_chunk(num_retries=5)
    if not response.get("id"):
        raise RuntimeError("O YouTube concluiu o upload sem devolver o ID")
    return response["id"]
