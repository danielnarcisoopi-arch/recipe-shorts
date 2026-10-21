from __future__ import annotations

import asyncio
import html
import logging
import re
import shutil
import subprocess
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
    """Find a sharp, freely licensed Commons photo and retain its credit."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "food-image.jpg"
    headers = {"User-Agent": "RecipeShorts/1.1 (recipe video; Wikimedia Commons API client)"}
    queries = [f'"{title}" food recipe']
    if ingredients:
        queries.append(" ".join(ingredients[:4]) + " ingredients food")
    try:
        for query in queries:
            params = {
                "action": "query", "generator": "search", "gsrsearch": query,
                "gsrnamespace": 6, "gsrlimit": 18, "prop": "imageinfo",
                "iiprop": "url|extmetadata", "iiurlwidth": 1400,
                "format": "json", "formatversion": 2,
            }
            response = requests.get("https://commons.wikimedia.org/w/api.php", params=params, headers=headers, timeout=20)
            response.raise_for_status()
            pages = (response.json().get("query") or {}).get("pages") or []
            for page in pages:
                info = (page.get("imageinfo") or [{}])[0]
                meta = info.get("extmetadata") or {}
                license_name = _metadata_text(meta.get("LicenseShortName", {}).get("value", ""))
                if not re.search(r"^(CC0|Public domain|CC BY(?:-SA)? [1-4](?:\.0)?)$", license_name, re.I):
                    continue
                url = info.get("thumburl") or info.get("url")
                if not url or not url.startswith("https://"):
                    continue
                image = requests.get(url, headers=headers, timeout=25)
                image.raise_for_status()
                if len(image.content) > 18_000_000 or not image.headers.get("Content-Type", "").startswith("image/"):
                    continue
                target.write_bytes(image.content)
                try:
                    with Image.open(target) as check:
                        if check.width < 500 or check.height < 350:
                            target.unlink(missing_ok=True)
                            continue
                        check.verify()
                except Exception:
                    target.unlink(missing_ok=True)
                    continue
                artist = _metadata_text(meta.get("Artist", {}).get("value", "Autor não indicado"))
                source_url = info.get("descriptionurl", "")
                log.info("Fotografia licenciada encontrada: %s", page.get("title"))
                return target, f"Imagem: {page.get('title')} — {artist} — {license_name}. {source_url}"
    except Exception as exc:
        log.warning("Não foi possível obter uma fotografia licenciada: %s", exc)
    return None, ""


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


def render_scene(label: str, text: str, image_path: Path | None, index: int, total: int, output: Path,
                 ingredient_list: list[str] | None = None) -> None:
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
    if image_path and image_path.exists():
        try:
            with Image.open(image_path) as source:
                photo = ImageOps.fit(source.convert("RGB"), (photo_box[2] - photo_box[0], photo_box[3] - photo_box[1]), method=Image.Resampling.LANCZOS)
            mask = Image.new("L", photo.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, photo.width - 1, photo.height - 1), radius=34, fill=255)
            im.paste(photo, (photo_box[0], photo_box[1]), mask)
        except Exception as exc:
            log.warning("Não foi possível apresentar a fotografia: %s", exc)
    else:
        # A labeled ingredient illustration keeps the scene useful when Commons has no match.
        d.text((540, 280), "ILUSTRAÇÃO DOS INGREDIENTES", font=_font(23, True), fill=CREAM, anchor="ma")
        ingredients = (ingredient_list or [line.removeprefix("• ") for line in text.splitlines() if line.strip()])[:6]
        colors = [(227, 183, 91), (231, 229, 210), (141, 176, 113), (198, 105, 77), (208, 164, 120), (118, 160, 169)]
        single_row = len(ingredients) <= 3
        card_width, gap = 270, 34
        row_width = len(ingredients) * card_width + max(0, len(ingredients) - 1) * gap
        start_x = (W - row_width) // 2 if single_row else 88
        for item_index, ingredient in enumerate(ingredients):
            col, row = (item_index, 0) if single_row else (item_index % 3, item_index // 3)
            x = start_x + col * (card_width + gap) if single_row else start_x + col * 304
            y0 = 365 if single_row else 345 + row * 310
            card_height = 500 if single_row else 270
            d.rounded_rectangle((x, y0, x + card_width, y0 + card_height), radius=25, fill=(43, 53, 46), outline=(82, 99, 83), width=2)
            cx, cy = x + card_width // 2, y0 + (190 if single_row else 103)
            item_lower = ingredient.lower()
            if any(word in item_lower for word in ("ovo", "egg")):
                d.ellipse((cx - 65, cy - 55, cx + 65, cy + 55), fill=(248, 244, 228), outline=(218, 215, 198), width=3)
                d.ellipse((cx - 25, cy - 24, cx + 25, cy + 25), fill=(GOLD), outline=(224, 158, 61), width=2)
            elif any(word in item_lower for word in ("leite", "milk", "natas", "cream")):
                d.rounded_rectangle((cx - 42, cy - 64, cx + 42, cy + 65), radius=12, fill=(220, 230, 223), outline=(250, 245, 232), width=3)
                d.rectangle((cx - 40, cy - 25, cx + 40, cy + 25), fill=(134, 173, 151))
            elif any(word in item_lower for word in ("farinha", "flour", "açúcar", "sugar", "sal", "rice", "arroz")):
                d.ellipse((cx - 72, cy + 14, cx + 72, cy + 65), fill=(190, 167, 135), outline=(225, 206, 176), width=3)
                d.ellipse((cx - 63, cy - 8, cx + 63, cy + 35), fill=(247, 235, 211), outline=(225, 206, 176), width=3)
            else:
                color = colors[item_index % len(colors)]
                d.ellipse((cx - 58, cy - 58, cx + 58, cy + 58), fill=color, outline=(238, 222, 193), width=3)
                d.ellipse((cx - 9, cy - 60, cx + 8, cy - 44), fill=(100, 130, 75))
            label_font = _font(17, True)
            labels = _wrap(ingredient, label_font, 230)[:2]
            label_y = y0 + (375 if single_row else 192)
            for line_index, line in enumerate(labels):
                d.text((cx, label_y + line_index * 24), line, font=label_font, fill=CREAM, anchor="ma")

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


def render(short: Short, destination: Path, work_dir: Path, voice: str = "pt-PT-RaquelNeural") -> tuple[float, str]:
    for name in ("ffmpeg", "ffprobe"):
        if not shutil.which(name):
            raise RuntimeError(f"É necessário instalar {name} para produzir os Shorts")
    work_dir.mkdir(parents=True, exist_ok=True)
    ingredient_names = [line.removeprefix("• ") for line in short.scenes[1][1].splitlines()]
    photo, credit = get_food_image(short.scenes[0][1], ingredient_names, work_dir)
    frames = []
    for i, (label, text) in enumerate(short.scenes):
        path = work_dir / f"scene-{i:02}.jpg"
        render_scene(label, text, photo, i, len(short.scenes), path, ingredient_names)
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
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(destination)]
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run(args)
    return duration, credit
