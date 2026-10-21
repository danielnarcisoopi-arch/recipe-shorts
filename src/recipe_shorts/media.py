from __future__ import annotations

import asyncio
import concurrent.futures
import html
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import edge_tts
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageFont

from .content import Short

log = logging.getLogger(__name__)
W, H = 1080, 1920
CREAM = (250, 245, 232)
MINT = (181, 226, 179)
GOLD = (241, 190, 102)


def _font(size: int, bold=False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _wrap(text: str, font, max_width: int) -> list[str]:
    words, rows, current = text.split(), [], ""
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for word in words:
        attempt = f"{current} {word}".strip()
        if probe.textbbox((0, 0), attempt, font=font)[2] <= max_width:
            current = attempt
        elif current:
            rows.append(current)
            current = word
        else:
            rows.append(word)
    if current:
        rows.append(current)
    return rows


def get_food_image(title: str, ingredients: list[str], folder: Path) -> tuple[Path | None, str]:
    """Find a real photo of the finished dish from Pixabay or Wikimedia Commons."""
    folder.mkdir(parents=True, exist_ok=True)
    terms = _translated_search_terms(title)
    queries = []
    for term in terms:
        queries.extend((term, f"{term} recipe", f"{term} plated food"))
    # If title search is weak, try a broad dish search informed by the actual ingredients.
    if ingredients:
        queries.append(" ".join(ingredients[:4]))
    return _find_food_photo(queries, folder / "finished-dish.jpg", minimum_size=(500, 350))


def _translated_search_terms(value: str) -> list[str]:
    """Return the original food name and an English search term when translation works."""
    clean = re.sub(r"\s+", " ", value).strip()
    terms = [clean] if clean else []
    if not clean:
        return terms
    try:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": "en", "dt": "t", "q": clean},
            headers={"User-Agent": "RecipeShorts/1.3"}, timeout=8,
        )
        response.raise_for_status()
        translated = "".join(part[0] for part in response.json()[0] if part and part[0])
        translated = re.sub(r"\s+", " ", translated).strip()
        if translated and translated.casefold() != clean.casefold():
            terms = [translated, clean]
    except Exception as exc:
        log.info("A pesquisa de imagens vai usar também o nome original '%s': %s", clean, exc)
    return list(dict.fromkeys(terms))


_IMAGE_CONTEXT_EXCLUSIONS = {
    "baby", "babies", "infant", "child", "children", "kid", "kids", "woman", "women", "man", "men",
    "boy", "boys", "girl", "girls", "person", "people", "family", "mother", "father", "parent",
    "portrait", "face", "drinking", "drink", "eating", "eat", "feeding", "breastfeeding", "nursing",
    "hand", "hands", "holding", "school", "classroom", "cartoon", "illustration", "drawing", "painting",
    "farm", "farmer", "farmers", "cattle", "cow", "cows", "calf", "calves", "hen", "hens", "rooster",
    "coop", "pasture", "milking", "logo", "poster", "advertisement", "advertising", "packaging", "label",
    "infographic", "diagram", "icon",
}
_IMAGE_QUERY_STOPWORDS = {
    "a", "an", "the", "of", "with", "and", "in", "on", "for", "to", "food", "foods", "ingredient",
    "ingredients", "photo", "photograph", "picture", "image", "recipe", "recipes", "plated", "fresh", "raw",
    "large", "small", "whole", "sliced", "chopped", "dried", "ground", "organic", "closeup", "close",
}


def _food_photo_relevant(query: str, description: str) -> bool:
    """Only accept photo metadata that names the requested food and avoids human/lifestyle contexts."""
    text = re.sub(r"[^a-z0-9]+", " ", description.lower())
    described = set(text.split())
    if described & _IMAGE_CONTEXT_EXCLUSIONS:
        return False
    words = [word for word in re.sub(r"[^a-z0-9]+", " ", query.lower()).split()
             if word not in _IMAGE_QUERY_STOPWORDS and len(word) > 1]
    wanted = list(dict.fromkeys(words))
    if not wanted:
        return False

    def matches(word: str) -> bool:
        variants = {word}
        if word.endswith("ies") and len(word) > 4:
            variants.add(word[:-3] + "y")
        elif word.endswith("s") and len(word) > 3:
            variants.add(word[:-1])
        return bool(variants & described)

    matched = sum(1 for word in wanted if matches(word))
    # Multiword dish searches must match most of the dish name; single ingredients must match exactly.
    required = max(1, (len(wanted) * 7 + 9) // 10)
    return matched >= required


def _ingredient_search_terms(ingredient: str) -> list[str]:
    clean = re.sub(r"\b\d+(?:[.,/]\d+)?\b|[½¼¾⅓⅔⅛⅜⅝⅞]", " ", ingredient.lower())
    clean = re.sub(
        r"\b(?:g|kg|mg|ml|cl|l|dl|oz|lb|cups?|tablespoons?|teaspoons?|tbsp|tsp|colheres?|chávenas?|xícaras?|sopa|chá|café|pinch|to taste|de|da|do|das|dos|q\.b\.)\b",
        " ", clean, flags=re.I,
    )
    clean = re.sub(r"[^\wÀ-ÿ -]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        clean = ingredient.strip()
    terms = _translated_search_terms(clean)
    return list(dict.fromkeys(re.sub(r"\s+", " ", re.sub(r"\b\d+(?:[.,/]\d+)?\b", " ", term)).strip()
                               for term in terms if term))


def _download_photo(url: str, target: Path, minimum_size: tuple[int, int], headers: dict[str, str]) -> bool:
    """Download and normalize an actual image; skip dead URLs, HTML, and tiny thumbnails."""
    try:
        response = requests.get(url, headers=headers, timeout=25)
        response.raise_for_status()
        if len(response.content) > 18_000_000 or not response.headers.get("Content-Type", "").startswith("image/"):
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".download")
        temporary.write_bytes(response.content)
        try:
            with Image.open(temporary) as source:
                if source.width < minimum_size[0] or source.height < minimum_size[1]:
                    return False
                rgba = source.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (250, 245, 232, 255))
                image = Image.alpha_composite(background, rgba).convert("RGB")
                image.save(target, format="JPEG", quality=92, optimize=True)
        finally:
            temporary.unlink(missing_ok=True)
        return target.is_file() and target.stat().st_size > 0
    except Exception as exc:
        log.info("Não foi possível descarregar a fotografia %s: %s", url, exc)
        target.unlink(missing_ok=True)
        return False


def _pixabay_cache_file(query: str) -> Path:
    cache_dir = Path(os.getenv("IMAGE_SEARCH_CACHE_DIR", "data/image-search-cache"))
    digest = hashlib.sha256(query.casefold().encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


def _pixabay_search(query: str, api_key: str) -> list[dict]:
    """Search and cache Pixabay metadata for 24 hours as required by its API terms."""
    cache_file = _pixabay_cache_file(query)
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(cached["fetched_at"])
        if datetime.now(timezone.utc) - fetched_at < timedelta(hours=24):
            return cached.get("hits", [])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    response = requests.get(
        "https://pixabay.com/api/",
        params={"key": api_key, "q": query[:100], "lang": "en", "image_type": "photo",
                "category": "food", "safesearch": "true", "min_width": 500,
                "min_height": 350, "per_page": 20},
        headers={"User-Agent": "RecipeShorts/1.3"}, timeout=20,
    )
    response.raise_for_status()
    hits = response.json().get("hits", [])
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = cache_file.with_suffix(".tmp")
    temp_file.write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "hits": hits}), encoding="utf-8")
    temp_file.replace(cache_file)
    return hits


def _find_pixabay_image(queries: list[str], target: Path, minimum_size=(320, 240)) -> tuple[Path | None, str]:
    """Search Pixabay's food-only photo catalog and accept only ingredient-matching tags."""
    api_key = os.getenv("PIXABAY_API_KEY", "").strip()
    if not api_key:
        return None, ""
    for query in queries:
        try:
            for item in _pixabay_search(query, api_key):
                if item.get("type") != "photo":
                    continue
                tags = str(item.get("tags") or "")
                if not _food_photo_relevant(query, tags):
                    continue
                if int(item.get("webformatWidth", 0)) < minimum_size[0] or int(item.get("webformatHeight", 0)) < minimum_size[1]:
                    continue
                url = item.get("largeImageURL") or item.get("webformatURL")
                if url and _download_photo(url, target, minimum_size, {"User-Agent": "RecipeShorts/1.3"}):
                    contributor = item.get("user", "Pixabay contributor")
                    page = item.get("pageURL", "https://pixabay.com/")
                    return target, f"Fotografia: {contributor} — Pixabay. {page}"
        except Exception as exc:
            log.info("Pixabay indisponível para '%s'; vou tentar o Commons: %s", query, exc)
    return None, ""


def _find_food_photo(queries: list[str], target: Path, minimum_size=(320, 240)) -> tuple[Path | None, str]:
    """Prefer Pixabay food photographs; Wikimedia Commons remains a fallback."""
    path, credit = _find_pixabay_image(queries, target, minimum_size)
    if path:
        return path, credit
    return _find_commons_image(queries, target, minimum_size)


def _find_commons_image(queries: list[str], target: Path, minimum_size=(320, 240)) -> tuple[Path | None, str]:
    """Search Commons for openly licensed ingredient and finished-dish photographs."""
    headers = {"User-Agent": "RecipeShorts/1.3 (open-license food photo search)"}
    target.parent.mkdir(parents=True, exist_ok=True)
    for query in queries:
        try:
            search = requests.get(
                "https://commons.wikimedia.org/w/api.php",
                params={"action": "query", "list": "search", "srnamespace": 6,
                        "srsearch": query, "srlimit": 20, "format": "json"},
                headers=headers, timeout=20,
            )
            search.raise_for_status()
            titles = [item["title"] for item in search.json().get("query", {}).get("search", []) if item.get("title")]
            if not titles:
                continue
            details = requests.get(
                "https://commons.wikimedia.org/w/api.php",
                params={"action": "query", "titles": "|".join(titles), "prop": "imageinfo",
                        "iiprop": "url|extmetadata", "iiurlwidth": 1000,
                        "format": "json", "formatversion": 2},
                headers=headers, timeout=20,
            )
            details.raise_for_status()
            for page in details.json().get("query", {}).get("pages", []):
                info = (page.get("imageinfo") or [{}])[0]
                meta = info.get("extmetadata") or {}
                image_description = _metadata_text(meta.get("ImageDescription", {}).get("value", ""))
                photo_description = f"{page.get('title', '')} {image_description}"
                if not _food_photo_relevant(query, photo_description):
                    continue
                license_name = _metadata_text(meta.get("LicenseShortName", {}).get("value", ""))
                if not re.search(r"^(CC0|Public domain|CC BY(?:-SA)? [1-4](?:\.0)?)$", license_name, re.I):
                    continue
                url = info.get("thumburl") or info.get("url")
                if not url or not url.startswith("https://"):
                    continue
                if not _download_photo(url, target, minimum_size, headers):
                    continue
                artist = _metadata_text(meta.get("Artist", {}).get("value", "Autor não indicado"))
                source_url = info.get("descriptionurl", "")
                return target, f"Imagem: {page.get('title')} — {artist} — {license_name}. {source_url}"
        except Exception as exc:
            log.info("Pesquisa Commons sem resultado para '%s': %s", query, exc)
    return None, ""


def get_ingredient_images(ingredients: list[str], folder: Path) -> tuple[dict[str, Path], list[str]]:
    """Search each listed ingredient separately for a real photo and its attribution."""
    folder.mkdir(parents=True, exist_ok=True)

    def fetch(index_item: tuple[int, str]):
        index, ingredient = index_item
        terms = _ingredient_search_terms(ingredient)
        # Bare terms are important: adding "food" to every query excluded many Commons titles.
        queries = [query for term in terms for query in (term, f"{term} ingredient", f"{term} food")]
        path, credit = _find_food_photo(queries, folder / f"ingredient-{index + 1}.jpg")
        return ingredient, path, credit

    photos: dict[str, Path] = {}
    credits: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, max(1, len(ingredients)))) as pool:
        futures = [pool.submit(fetch, item) for item in enumerate(ingredients[:6])]
        for future in futures:
            ingredient, path, credit = future.result()
            if path:
                photos[ingredient] = path
                credits.append(credit)
    log.info("Fotografias reais de ingredientes encontradas: %d/%d", len(photos), min(6, len(ingredients)))
    return photos, credits


def _metadata_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(value))).strip()


def _background(scene_index: int) -> Image.Image:
    bg = Image.new("RGB", (W, H), (24, 30, 27))
    decor = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(decor)
    offset = (scene_index * 97) % 180
    d.ellipse((785 - offset, 1020 + offset, 1320, 1570 + offset), fill=(93, 126, 79, 34))
    decor = decor.filter(ImageFilter.GaussianBlur(100))
    return Image.alpha_composite(bg.convert("RGBA"), decor).convert("RGB")


def _draw_ingredient_grid(im: Image.Image, ingredients: list[str], photos: dict[str, Path]) -> None:
    d = ImageDraw.Draw(im)
    heading = "FOTOGRAFIAS DOS INGREDIENTES"
    d.text((540, 278), heading, font=_font(23, True), fill=CREAM, anchor="ma")
    items = ingredients[:6]
    single_row = len(items) <= 3
    card_w, gap = 282, 20
    start_x = (W - (len(items) * card_w + max(0, len(items) - 1) * gap)) // 2 if single_row else 86
    for i, name in enumerate(items):
        col, row = (i, 0) if single_row else (i % 3, i // 3)
        x = start_x + col * (card_w + gap) if single_row else start_x + col * 304
        y = 350 if single_row else 338 + row * 324
        card_h = 570 if single_row else 300
        d.rounded_rectangle((x, y, x + card_w, y + card_h), radius=22, fill=(43, 53, 46), outline=(82, 99, 83), width=2)
        image_h = card_h - 82
        path = photos.get(name)
        if path and path.exists():
            try:
                with Image.open(path) as source:
                    tile = ImageOps.fit(source.convert("RGB"), (card_w - 12, image_h), method=Image.Resampling.LANCZOS)
                mask = Image.new("L", tile.size, 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, tile.width - 1, tile.height - 1), radius=17, fill=255)
                im.paste(tile, (x + 6, y + 6), mask)
            except Exception as exc:
                log.info("Não foi possível abrir a fotografia de '%s': %s", name, exc)
                path = None
        if not path or not path.exists():
            d.text((x + card_w // 2, y + image_h // 2), "Fotografia não\ndisponível", font=_font(19, True),
                   fill=(186, 197, 181), anchor="mm", align="center")
        lines = _wrap(name, _font(16, True), card_w - 20)[:2]
        label_y = y + card_h - 66
        for line_no, line in enumerate(lines):
            d.text((x + card_w // 2, label_y + line_no * 22), line, font=_font(16, True), fill=CREAM, anchor="ma")


def _draw_final_dish_placeholder(draw: ImageDraw.ImageDraw) -> None:
    draw.rounded_rectangle((100, 430, 980, 850), radius=30, fill=(43, 53, 46), outline=(82, 99, 83), width=3)
    draw.text((540, 590), "FOTOGRAFIA DO PRATO", font=_font(32, True), fill=CREAM, anchor="mm")
    draw.text((540, 655), "não encontrada nesta biblioteca", font=_font(25), fill=(186, 197, 181), anchor="mm")


def render_scene(label: str, text: str, image_path: Path | None, index: int, total: int, output: Path,
                 ingredient_list: list[str] | None = None,
                 ingredient_photos: dict[str, Path] | None = None) -> None:
    im = _background(index)
    d = ImageDraw.Draw(im)
    d.text((64, 66), "PANELA", font=_font(33, True), fill=CREAM)
    d.text((1014, 77), f"{index + 1:02d} / {total:02d}", font=_font(23, True), fill=MINT, anchor="ra")
    d.text((66, 126), "RECEITAS COM HISTÓRIA", font=_font(20, True), fill=(186, 197, 181))
    gap, y = 8, 190
    bar_width = (948 - gap * (total - 1)) // total
    for n in range(total):
        x1 = 66 + n * (bar_width + gap)
        d.rounded_rectangle((x1, y, x1 + bar_width, y + 7), radius=4,
                            fill=GOLD if n == index else (94, 103, 95))

    photo_box = (66, 252, 1014, 1016)
    d.rounded_rectangle(photo_box, radius=34, fill=(47, 56, 49))
    ingredient_list = ingredient_list or [line.removeprefix("• ") for line in text.splitlines() if line.strip()]
    ingredient_photos = ingredient_photos or {}
    if label.upper() == "INGREDIENTES" and ingredient_list:
        _draw_ingredient_grid(im, ingredient_list, ingredient_photos)
    elif image_path and image_path.exists():
        try:
            with Image.open(image_path) as source:
                photo = ImageOps.fit(source.convert("RGB"), (photo_box[2] - photo_box[0], photo_box[3] - photo_box[1]), method=Image.Resampling.LANCZOS)
            mask = Image.new("L", photo.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, photo.width - 1, photo.height - 1), radius=34, fill=255)
            im.paste(photo, (photo_box[0], photo_box[1]), mask)
        except Exception as exc:
            log.warning("Não foi possível apresentar a fotografia: %s", exc)
            if label.upper() == "O PRATO FINAL":
                _draw_final_dish_placeholder(d)
    elif label.upper() == "O PRATO FINAL":
        _draw_final_dish_placeholder(d)
    else:
        _draw_ingredient_grid(im, ingredient_list, ingredient_photos)

    label = label.upper()
    d.text((66, 1073), label, font=_font(25, True), fill=GOLD)
    lines: list[str] = []
    for paragraph in text.splitlines():
        if paragraph.strip():
            font = _font(35 if label == "INGREDIENTES" else 46, label != "INGREDIENTES")
            lines.extend(_wrap(paragraph, font, 930))
        else:
            lines.append("")
    body_font = _font(35 if label == "INGREDIENTES" else (52 if len(text) < 55 else 43), label != "INGREDIENTES")
    line_height = 51 if label == "INGREDIENTES" else 61
    content_y = 1127
    for line in lines[:8 if label == "INGREDIENTES" else 7]:
        d.text((66, content_y), line, font=body_font, fill=CREAM)
        content_y += line_height
    footer_y = max(1500, min(1662, content_y + 72))
    d.line((66, footer_y, 1014, footer_y), fill=(87, 100, 89), width=2)
    d.text((66, footer_y + 40), "COZINHA  ·  MEMÓRIA  ·  SABOR", font=_font(22, True), fill=CREAM)
    d.text((66, footer_y + 88), "Receita histórica · fonte e notas na descrição", font=_font(19), fill=(186, 197, 181))
    output.parent.mkdir(parents=True, exist_ok=True)
    im.save(output, quality=94)


async def _speak(text: str, voice: str, output: Path) -> None:
    await edge_tts.Communicate(text, voice).save(str(output))


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def verify_shorts_format(video_path: Path) -> dict[str, float | int]:
    """Check the encoded file is vertical and within the project's Short duration limit."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video_path)],
        check=True, capture_output=True, text=True,
    )
    probe = json.loads(result.stdout)
    stream = next((item for item in probe.get("streams", []) if item.get("codec_type") == "video"), None)
    if not stream:
        raise RuntimeError("O ficheiro criado não contém uma faixa de vídeo")
    width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
    duration = float(probe.get("format", {}).get("duration", 0))
    if width <= 0 or height < width:
        raise RuntimeError(f"O vídeo tem formato {width}x{height}; um Short tem de ser vertical ou quadrado")
    if duration <= 0 or duration > 60:
        raise RuntimeError(f"O vídeo tem {duration:.1f}s; o limite validado para este Short é 60s")
    return {"width": width, "height": height, "duration_seconds": duration}


def render(short: Short, destination: Path, work_dir: Path, voice: str = "pt-PT-RaquelNeural") -> tuple[float, str]:
    for name in ("ffmpeg", "ffprobe"):
        if not shutil.which(name):
            raise RuntimeError(f"É necessário instalar {name} para produzir os Shorts")
    work_dir.mkdir(parents=True, exist_ok=True)
    ingredient_names = [line.removeprefix("• ") for line in short.scenes[1][1].splitlines()]
    photo, credit = get_food_image(short.scenes[0][1], ingredient_names, work_dir)
    ingredient_photos, ingredient_credits = get_ingredient_images(ingredient_names, work_dir / "ingredients")
    frames = []
    for i, (label, text) in enumerate(short.scenes):
        path = work_dir / f"scene-{i:02}.jpg"
        render_scene(label, text, photo, i, len(short.scenes), path, ingredient_names, ingredient_photos)
        frames.append(path)
    audio = work_dir / "voice.mp3"
    asyncio.run(_speak(short.narration, voice, audio))
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio)], check=True, capture_output=True, text=True)
    duration = float(probe.stdout.strip())
    if duration < 20 or duration > 58:
        raise RuntimeError(f"Narração fora do intervalo de Shorts confortável ({duration:.1f}s); não vou publicar este guião")
    weights = [max(1, len(text.split())) for _, text in short.scenes]
    scene_seconds = [duration * n / sum(weights) for n in weights]
    args = ["ffmpeg", "-y", "-loglevel", "error"]
    for frame, secs in zip(frames, scene_seconds):
        args += ["-loop", "1", "-framerate", "30", "-t", f"{secs:.3f}", "-i", str(frame)]
    args += ["-i", str(audio)]
    count = len(frames)
    filters = "".join(
        f"[{i}:v]scale=1080:1920,zoompan=z='min(zoom+0.00035,1.03)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v{i}];"
        for i in range(count)
    )
    filters += "".join(f"[v{i}]" for i in range(count)) + f"concat=n={count}:v=1:a=0[v]"
    args += ["-filter_complex", filters, "-map", "[v]", "-map", f"{count}:a:0", "-t", f"{duration:.3f}",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
             "-aspect", "9:16", "-metadata:s:v:0", "rotate=0",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(destination)]
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run(args)
    short_info = verify_shorts_format(destination)
    log.info("Formato verificado para Shorts: %(width)dx%(height)d · %(duration_seconds).1fs", short_info)
    credits = [item for item in [credit, *ingredient_credits] if item]
    return duration, "\n".join(credits)
