from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests

log = logging.getLogger(__name__)
BASE = "https://raw.githubusercontent.com/AdamBouhmad/open-recipe-archive/main"
INDEX_URL = f"{BASE}/index/collections.json"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS recipes (id TEXT PRIMARY KEY, title TEXT, collection TEXT, culture TEXT, author TEXT, body TEXT, source_title TEXT, source_url TEXT, source_year TEXT, license TEXT, tags TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS published (id TEXT PRIMARY KEY, published_at TEXT NOT NULL, video_id TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS sync_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS recipes_collection ON recipes(collection)")
    return db


def sync_library(db_path: Path, wanted: list[str], timeout: int = 30) -> int:
    """Sync structured JSONL collections and retain license/provenance for each row."""
    db = _db(db_path)
    try:
        cached = db.execute("SELECT value FROM sync_state WHERE key='last_sync'").fetchone()
        count = db.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
        if cached and count:
            last_sync = datetime.fromisoformat(cached[0])
            if datetime.now(timezone.utc) - last_sync < timedelta(days=7):
                return count
    finally:
        db.close()
    session = requests.Session()
    session.headers.update({"User-Agent": "RecipeShorts/1.0 (automated recipe video project)"})
    response = session.get(INDEX_URL, timeout=timeout)
    response.raise_for_status()
    index = response.json()
    collections = index if isinstance(index, list) else index.get("collections", [])
    wanted_set = {_slug(x) for x in wanted}
    db = _db(db_path)
    added = 0
    try:
        for item in collections:
            slug = item.get("slug") or item.get("id") or _slug(item.get("name", ""))
            if not slug:
                continue
            names = {_slug(str(item.get(k, ""))) for k in ("slug", "id", "name", "collection_name", "country", "country_name") if item.get(k)}
            if not names.intersection(wanted_set) and not any(w in name for w in wanted_set for name in names):
                continue
            url = f"{BASE}/collections/{slug}/recipes.jsonl"
            try:
                result = session.get(url, timeout=timeout)
                if result.status_code == 404:
                    log.info("Collection has no bulk export: %s", slug)
                    continue
                result.raise_for_status()
                for line in result.text.splitlines():
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    title, body = str(r.get("title", "")).strip(), str(r.get("body", "")).strip()
                    if not title or not body:
                        continue
                    license_name = str(r.get("license", "")).strip().lower()
                    # Avoid relying on ambiguous or restrictive rows.
                    if license_name not in {"public-domain", "cc0-1.0", "cc0", "unlicense"}:
                        continue
                    rid = hashlib.sha256(f"{slug}\0{r.get('slug', title)}".encode()).hexdigest()
                    db.execute("INSERT OR IGNORE INTO recipes VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                        rid, title, str(r.get("collection_name") or slug), str(r.get("culture", "")),
                        str(r.get("author", "")), body, str(r.get("source_title", "")),
                        str(r.get("source_url", "")), str(r.get("source_year", "")), license_name,
                        json.dumps(r.get("tags", []), ensure_ascii=False)))
                    added += db.execute("SELECT changes()").fetchone()[0]
            except requests.RequestException as exc:
                log.warning("Could not sync %s: %s", slug, exc)
        db.commit()
        count = db.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
        if count < 100:
            raise RuntimeError(f"Recipe library sync returned only {count} usable public-domain records; refusing to publish")
        db.execute("INSERT OR REPLACE INTO sync_state VALUES ('last_sync',?)", (datetime.now(timezone.utc).isoformat(),))
        db.commit()
        log.info("Recipe catalog ready: %d public-domain recipes (%d newly added)", count, added)
        return count
    finally:
        db.close()


def _sections(body: str) -> tuple[list[str], list[str]]:
    """Read headings/list items in common archive Markdown variants."""
    lines = [re.sub(r"\s+", " ", ln.strip()) for ln in body.splitlines()]
    section = ""
    ingredients: list[str] = []
    steps: list[str] = []
    for line in lines:
        clean = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s*", "", line).strip()
        head = re.sub(r"[#:*_ ]", "", line).lower()
        is_heading = line.startswith("#") or (len(line) < 60 and line.endswith(":") and not line[:1].isdigit())
        if is_heading:
            if any(x in head for x in ("ingredient", "materials")):
                section = "ingredients"
            elif any(x in head for x in ("direction", "instruction", "method", "preparation", "procedure", "receipt")):
                section = "steps"
            else:
                section = ""
            continue
        if line.startswith("#") or not clean:
            continue
        clean = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", clean)
        clean = re.sub(r"`([^`]+)`", r"\1", clean)
        if section == "ingredients" and (line.startswith(("-", "*", "+")) or re.match(r"\d+[.)]", line)):
            ingredients.append(clean)
        elif section == "steps" and len(clean) > 12:
            steps.append(clean)
    return ingredients, steps


def choose_recipe(db_path: Path, collections: list[str]) -> dict:
    db = _db(db_path)
    try:
        clauses, params = [], []
        for name in collections:
            clauses.append("lower(collection) LIKE ? OR lower(culture) LIKE ? OR lower(tags) LIKE ?")
            p = f"%{name.lower()}%"
            params.extend((p, p, p))
        where = " OR ".join(f"({c})" for c in clauses) if clauses else "1=1"
        rows = db.execute(f"SELECT id,title,collection,culture,author,body,source_title,source_url,source_year,license,tags FROM recipes WHERE {where} AND id NOT IN (SELECT id FROM published) ORDER BY RANDOM() LIMIT 120", params).fetchall()
        candidates = []
        for row in rows:
            rec = dict(zip(("id", "title", "collection", "culture", "author", "body", "source_title", "source_url", "source_year", "license", "tags"), row))
            rec["ingredients"], rec["steps"] = _sections(rec["body"])
            word_count = sum(len(x.split()) for x in rec["ingredients"] + rec["steps"])
            if 3 <= len(rec["ingredients"]) <= 6 and 1 <= len(rec["steps"]) <= 8 and 25 <= word_count <= 105 and max(len(x.split()) for x in rec["steps"]) <= 35:
                candidates.append(rec)
        if not candidates:
            # Broaden the sample within the selected cuisines, never across languages/cultures.
            fallback_clauses = []
            fallback_params = []
            for name in collections:
                like = f"%{name.lower()}%"
                fallback_clauses.append("lower(collection) LIKE ? OR lower(culture) LIKE ? OR lower(tags) LIKE ?")
                fallback_params.extend((like, like, like))
            fallback_where = " OR ".join(f"({x})" for x in fallback_clauses) if fallback_clauses else "1=1"
            query = ("SELECT id,title,collection,culture,author,body,source_title,source_url,source_year,license,tags "
                     f"FROM recipes WHERE ({fallback_where}) AND id NOT IN (SELECT id FROM published) ORDER BY RANDOM() LIMIT 1000")
            for row in db.execute(query, fallback_params):
                rec = dict(zip(("id", "title", "collection", "culture", "author", "body", "source_title", "source_url", "source_year", "license", "tags"), row))
                rec["ingredients"], rec["steps"] = _sections(rec["body"])
                word_count = sum(len(x.split()) for x in rec["ingredients"] + rec["steps"])
                if 3 <= len(rec["ingredients"]) <= 6 and 1 <= len(rec["steps"]) <= 8 and 25 <= word_count <= 105 and max(len(x.split()) for x in rec["steps"]) <= 35:
                    candidates.append(rec)
        if not candidates:
            raise RuntimeError("No unused recipe has a readable ingredient list and directions")
        return candidates[0]
    finally:
        db.close()


def mark_published(db_path: Path, recipe_id: str, published_at: str, video_id: str) -> None:
    db = _db(db_path)
    try:
        db.execute("INSERT OR REPLACE INTO published VALUES (?,?,?)", (recipe_id, published_at, video_id))
        db.commit()
    finally:
        db.close()
