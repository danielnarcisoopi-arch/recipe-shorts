from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .content import build_short
from .library import _db, choose_recipe, mark_published, sync_library
from .media import render
from .youtube import upload

log = logging.getLogger("recipe_shorts")


def _slot(now: datetime, timezone: str, hours: list[int]) -> str | None:
    local = now.astimezone(ZoneInfo(timezone))
    if local.hour not in hours or local.minute > 20:
        return None
    return f"{local.date().isoformat()}-{local.hour:02d}"


def run(force: bool = False, upload_enabled: bool | None = None) -> Path | None:
    timezone = os.getenv("TIMEZONE", "Europe/Lisbon")
    hours = [int(x.strip()) for x in os.getenv("PUBLISH_HOURS", "8,11,14,17,20,22").split(",") if x.strip()]
    now = datetime.now(ZoneInfo(timezone))
    slot = _slot(now, timezone, hours)
    enabled = os.getenv("UPLOAD_ENABLED", "false").lower() in {"true", "1", "yes"} if upload_enabled is None else upload_enabled
    if not force and slot is None:
        log.info("Fora das seis janelas locais; sem vídeo neste ciclo (%s)", now.strftime("%H:%M %Z"))
        return None

    data = Path(os.getenv("DATA_DIR", "data"))
    output = Path(os.getenv("OUTPUT_DIR", "output"))
    db_file = data / "recipes.sqlite3"
    collections = [x.strip() for x in os.getenv("RECIPE_COLLECTIONS", "portugal,brazil").split(",") if x.strip()]
    sync_library(db_file, collections)
    if slot:
        db = _db(db_file)
        try:
            exists = db.execute("SELECT 1 FROM published WHERE id=?", ("slot:" + slot,)).fetchone()
        finally:
            db.close()
        if exists:
            log.info("A publicação deste horário já está registada: %s", slot)
            return None

    recipe = choose_recipe(db_file, collections)
    short = build_short(recipe)
    stamp = now.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
    video_path = output / f"recipe-{stamp}.mp4"
    duration, image_credit = render(short, video_path, data / "render" / stamp, os.getenv("TTS_VOICE", "pt-PT-FernandaNeural"))
    if image_credit:
        short.description += "\n" + image_credit
    metadata = {"recipe_id": recipe["id"], "recipe_title": recipe["title"], "collection": recipe["collection"],
                "source_title": recipe["source_title"], "source_url": recipe["source_url"], "license": recipe["license"],
                "video": str(video_path), "duration_seconds": round(duration, 2), "local_time": now.isoformat(),
                "image_credit": image_credit, "youtube_video_id": None}
    meta_path = output / f"recipe-{stamp}.json"
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Vídeo criado: %s · %s · %.1fs", video_path, recipe["title"], duration)
    if enabled:
        video_id = upload(video_path, short, os.getenv("YOUTUBE_TOKEN_JSON", ""),
                          os.getenv("EXPECTED_YOUTUBE_CHANNEL_ID", ""),
                          os.getenv("YOUTUBE_PRIVACY_STATUS", "public"),
                          os.getenv("YOUTUBE_NOTIFY_SUBSCRIBERS", "false").lower() == "true")
        metadata["youtube_video_id"] = video_id
        meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        # Keep one deterministic slot marker and recipe ID to prevent duplicate uploads after retries.
        mark_published(db_file, recipe["id"], now.isoformat(), video_id)
        if slot:
            db = _db(db_file)
            try:
                db.execute("INSERT OR REPLACE INTO published VALUES (?,?,?)", ("slot:" + slot, now.isoformat(), video_id))
                db.commit()
            finally:
                db.close()
        log.info("Publicado: https://youtube.com/shorts/%s", video_id)
    return video_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerar Shorts de receitas históricas")
    parser.add_argument("--force", action="store_true", help="ignorar o horário para gerar uma pré-visualização manual")
    parser.add_argument("--publish", action="store_true", help="autorizar publicação nesta execução manual")
    args = parser.parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    run(force=args.force, upload_enabled=True if args.publish else None)


if __name__ == "__main__":
    main()
