from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import shutil
import subprocess
from pathlib import Path

import edge_tts
import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from .content import Short

log = logging.getLogger(__name__)
W, H = 1080, 1920
BG = (19, 24, 23)
CREAM = (250, 245, 232)
MINT = (181, 226, 179)
GOLD = (241, 190, 102)


def _font(size: int, bold=False):
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(p, size)
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
    if current:
        rows.append(current)
    return rows


def get_food_image(query: str, folder: Path) -> tuple[Path | None, str]:
    """Find a freely licensed Wikimedia Commons food image and retain attribution."""
    folder.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(query.casefold().encode("utf-8")).hexdigest()[:12]
    target = folder / f"commons-{key}.jpg"
    if target.exists():
        return target, ""
    params = {"action": "query", "generator": "search", "gsrsearch": f'filetype:bitmap "{query}" food',
              "gsrnamespace": 6, "gsrlimit": 10, "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 1200,
              "format": "json", "origin": "*"}
    headers = {"User-Agent": "RecipeShorts/1.0 (recipe videos; contact: recipe-shorts project)"}
    try:
        res = requests.get("https://commons.wikimedia.org/w/api.php", params=params, headers=headers, timeout=20)
        res.raise_for_status()
        pages = (res.json().get("query") or {}).get("pages") or {}
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            license_name = meta.get("LicenseShortName", {}).get("value", "")
            if not re.search(r"^(CC0|Public domain|CC BY(?:-SA)? [234].0)$", license_name, re.I):
                continue
            url = info.get("thumburl") or info.get("url")
            if not url or not url.startswith("https://"):
                continue
            img = requests.get(url, headers=headers, timeout=25)
            img.raise_for_status()
            if len(img.content) > 18_000_000:
                continue
            target.write_bytes(img.content)
            with Image.open(target) as check:
                check.verify()
            credit = meta.get("Artist", {}).get("value", "Autor nÃ£o indicado")
            credit = re.sub(r"<[^>]+>", "", credit)
            source_url = info.get("descriptionurl", "")
            return target, f"Imagem: {page.get('title')} â€” {credit} â€” {license_name}. {source_url}"
    except Exception as exc:
        log.info("No suitable Commons image; using original graphic treatment: %s", exc)
    return None, ""


def _ingredient_label(value: str) -> str:
    value = re.sub(r"^\s*[\dÂ½Â¼Â¾.,/]+\s*", "", value)
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.sub(r"\b(?:chÃ¡venas?|colheres?|xÃ­caras?|cups?|tablespoons?|teaspoons?|g|kg|mg|ml|cl|l|litros?|gramas?|quilos?|dentes?|pitadas?|unidades?)\b", " ", value, flags=re.I)
    value = re.sub(r"\b(?:de|do|da|dos|das|de um|de uma)\b", " ", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" ,.;:")
    return value[:42]


def _ingredient_collage(items: list[tuple[Path, str]], destination: Path) -> Path | None:
    """Build a clear 2x2 photo board from licensed ingredient images."""
    if len(items) < 2:
        return None
    canvas = Image.new("RGB", (1200, 820), (30, 38, 33))
    draw = ImageDraw.Draw(canvas)
    tile_w, tile_h, gap, margin = 574, 390, 16, 10
    for i, (path, label) in enumerate(items[:4]):
        x = margin + (i % 2) * (tile_w + gap)
        y = margin + (i // 2) * (tile_h + gap)
        try:
            with Image.open(path) as source:
                tile = ImageOps.fit(source.convert("RGB"), (tile_w, tile_h), method=Image.Resampling.LANCZOS)
        except Exception:
            continue
        canvas.paste(tile, (x, y))
        draw.rectangle((x, y + tile_h - 64, x + tile_w, y + tile_h), fill=(15, 21, 17))
        draw.text((x + 18, y + tile_h - 53), label.upper(), font=_font(28, True), fill=CREAM)
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, quality=92)
    return destination


def _background(image_path: Path | None, scene_index: int) -> Image.Image:
    if image_path:
        try:
            with Image.open(image_path) as source:
                bg = ImageOps.fit(source.convert("RGB"), (W, H), method=Image.Resampling.LANCZOS)
            bg = ImageEnhance.Color(bg).enhance(0.72).filter(ImageFilter.GaussianBlur(7))
            # Dark gradient keeps the text legible without a heavy interface panel.
            overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            gradient = Image.new("L", (1, H))
            gradient.putdata([int(90 + min(125, max(0, (y - 300) * 0.09))) for y in range(H)])
            alpha_layer = gradient.resize((W, H))
            overlay.putalpha(alpha_layer)
            overlay = Image.merge("RGBA", (Image.new("L", (W, H), 11), Image.new("L", (W, H), 18), Image.new("L", (W, H), 16), alpha_layer))
            return Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
        except Exception:
            pass
    # Original vector-like background is stable and self-contained when no licensed photo is available.
    bg = Image.new("RGB", (W, H), BG)
    decor = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(decor)
    offset = (scene_index * 173) % 430
    d.ellipse((690-offset//3, 250+offset, 1320, 880+offset), fill=(106, 146, 95, 85))
    d.ellipse((-300+offset//4, 1050-offset//5, 440, 1800), fill=(189, 132, 69, 55))
    decor = decor.filter(ImageFilter.GaussianBlur(95))
    result = Image.alpha_composite(bg.convert("RGBA"), decor).convert("RGB")
    # Neutral line-art plate gives the fallback a food/editorial anchor without pretending to show the dish.
    line = ImageDraw.Draw(result)
    line.ellipse((344, 346, 736, 738), outline=(230, 220, 196), width=7)
    line.ellipse((386, 388, 694, 696), outline=(181, 226, 179), width=4)
    line.ellipse((428, 430, 652, 654), outline=(241, 190, 102), width=3)
    line.arc((475, 470, 610, 585), 205, 335, fill=(230, 220, 196), width=5)
    line.arc((495, 452, 620, 574), 210, 340, fill=(230, 220, 196), width=5)
    line.ellipse((524, 486, 560, 523), outline=(181, 226, 179), width=4)
    return result


def render_scene(label: str, text: str, image_path: Path | None, index: int, total: int, output: Path) -> None:
    im = _background(image_path, index)
    d = ImageDraw.Draw(im)
    # Small editorial masthead and progress ribbon.
    d.rounded_rectangle((66, 104, 230, 158), radius=20, fill=(250, 245, 232))
    d.text((91, 113), "PANELA", font=_font(24, True), fill=(28, 43, 34))
    d.text((66, 194), "RECEITAS DE ARQUIVO", font=_font(24, True), fill=MINT)
    y = 226
    gap = 8
    bar_width = max(22, (948 - gap * (total - 1)) // total)
    for n in range(total):
        x1 = 66 + n * (bar_width + gap)
        d.rounded_rectangle((x1, y, x1 + bar_width, y + 8), radius=4,
                            fill=GOLD if n == index else (235, 229, 216, 115))
    d.text((66, 296), label.upper(), font=_font(31, True), fill=GOLD)
    # Show a sharp, framed photo over the blurred full-screen backdrop.
    if image_path and image_path.exists():
        try:
            with Image.open(image_path) as source:
                card = ImageOps.fit(source.convert("RGB"), (948, 690), method=Image.Resampling.LANCZOS)
            mask = Image.new("L", card.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, card.width - 1, card.height - 1), radius=34, fill=255)
            im.paste(card, (66, 354), mask)
            d = ImageDraw.Draw(im)
        except Exception:
            pass
    body_font = _font(54 if len(text) < 105 else 44, True)
    rows = _wrap(text, body_font, 930)
    line_height = 70 if body_font.size > 48 else 59
    content_y = 1095
    for line in rows[:8]:
        d.text((66, content_y), line, font=body_font, fill=CREAM, stroke_width=1, stroke_fill=(10, 15, 13))
        content_y += line_height
    d.line((66, 1630, 1014, 1630), fill=(250, 245, 232, 120), width=2)
    d.text((66, 1670), "COZINHA â€¢ MEMÃ“RIA â€¢ SABOR", font=_font(24, True), fill=CREAM)
    d.text((66, 1742), "Receita histÃ³rica Â· confira as notas na descriÃ§Ã£o", font=_font(21), fill=(226, 222, 210))
    output.parent.mkdir(parents=True, exist_ok=True)
    im.save(output, quality=94)


async def _speak(text: str, voice: str, output: Path) -> None:
    # Prefer the requested voice and relaxed prosody; fall back to the known PT-PT female voice
    # if Edge's voice catalogue does not return audio for the selected voice.
    fallback = "pt-PT-RaquelNeural"
    profiles = [(voice, "-4%", "-1Hz"), (voice, None, None)]
    if voice != fallback:
        profiles.extend([(fallback, "-4%", "-1Hz"), (fallback, None, None)])
    failures = []
    for candidate_voice, rate, pitch in profiles:
        for attempt in range(2):
            output.unlink(missing_ok=True)
            try:
                if rate is None:
                    communicate = edge_tts.Communicate(text, candidate_voice)
                else:
                    communicate = edge_tts.Communicate(text, candidate_voice, rate=rate, pitch=pitch)
                await communicate.save(str(output))
                if output.exists() and output.stat().st_size > 0:
                    if candidate_voice != voice:
                        log.warning("A voz %s nÃ£o devolveu Ã¡udio; usei a voz feminina de reserva %s", voice, candidate_voice)
                    return
                raise RuntimeError("Edge TTS devolveu um ficheiro de Ã¡udio vazio")
            except Exception as exc:
                failures.append(f"{candidate_voice} ({'prosÃ³dia ajustada' if rate else 'predefiniÃ§Ãµes'}): {exc}")
                log.warning("Falha de sÃ­ntese com %s (tentativa %d): %s", candidate_voice, attempt + 1, exc)
                if attempt == 0:
                    await asyncio.sleep(1)
    raise RuntimeError("O serviÃ§o de voz nÃ£o devolveu Ã¡udio apÃ³s as tentativas: " + " | ".join(failures[-4:]))


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def render(short: Short, destination: Path, work_dir: Path, voice: str = "pt-PT-FernandaNeural") -> tuple[float, str]:
    for name in ("ffmpeg", "ffprobe"):
        if not shutil.which(name):
            raise RuntimeError(f"Ã‰ necessÃ¡rio instalar {name} para produzir os Shorts")
    work_dir.mkdir(parents=True, exist_ok=True)
    photo_dir = work_dir / "commons"
    photo, credit = get_food_image(f"{short.recipe['title']} finished dish", photo_dir)
    ingredient_photos: list[tuple[Path, str]] = []
    credits = [credit] if credit else []
    for raw in short.recipe.get("ingredients", [])[:4]:
        label = _ingredient_label(raw)
        if not label:
            continue
        path, item_credit = get_food_image(label, photo_dir)
        if path:
            ingredient_photos.append((path, label))
        if item_credit:
            credits.append(item_credit)
    collage = _ingredient_collage(ingredient_photos, work_dir / "ingredient-collage.jpg")
    frames = []
    for i, (label, text) in enumerate(short.scenes):
        path = work_dir / f"scene-{i:02}.jpg"
        visual = collage if label == "INGREDIENTES" and collage else photo
        render_scene(label, text, visual, i, len(short.scenes), path)
        frames.append(path)
    audio = work_dir / "voice.mp3"
    asyncio.run(_speak(short.narration, voice, audio))
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio)], check=True, capture_output=True, text=True)
    duration = float(probe.stdout.strip())
    if duration < 20 or duration > 58:
        raise RuntimeError(f"NarraÃ§Ã£o fora do intervalo de Shorts confortÃ¡vel ({duration:.1f}s); nÃ£o vou publicar este guiÃ£o")
    # Split scene time using words in each visual beat; the complete narration remains audible.
    weights = [max(1, len(text.split())) for _, text in short.scenes]
    scene_seconds = [duration * n / sum(weights) for n in weights]
    args = ["ffmpeg", "-y", "-loglevel", "error"]
    for image, secs in zip(frames, scene_seconds):
        args += ["-loop", "1", "-framerate", "30", "-t", f"{secs:.3f}", "-i", str(image)]
    args += ["-i", str(audio)]
    n = len(frames)
    filters = "".join(f"[{i}:v]scale=1080:1920,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v{i}];" for i in range(n))
    filters += "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    args += ["-filter_complex", filters, "-map", "[v]", "-map", f"{n}:a:0", "-t", f"{duration:.3f}",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(destination)]
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run(args)
    return duration, "\n".join(dict.fromkeys(credits))
