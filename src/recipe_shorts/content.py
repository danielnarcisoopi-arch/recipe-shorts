from __future__ import annotations

import re
from dataclasses import dataclass

import requests


@dataclass
class Short:
    recipe: dict
    title: str
    narration: str
    description: str
    tags: list[str]
    scenes: list[tuple[str, str]]


def _plain(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*_`#]", "", value)).strip()


_translation_cache: dict[str, str] = {}


def _portuguese(value: str) -> str:
    """Translate source text to Portuguese; fail closed instead of publishing mixed-language copy."""
    value = _plain(value)
    if not value:
        return value
    if value not in _translation_cache:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": "pt-PT", "dt": "t", "q": value},
            headers={"User-Agent": "RecipeShorts/1.0"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        translated = "".join(part[0] for part in payload[0] if part and part[0])
        if not translated.strip():
            raise RuntimeError("Não foi possível traduzir a receita integralmente para português")
        _translation_cache[value] = _plain(translated)
    return _translation_cache[value]


def build_short(recipe: dict) -> Short:
    # Keep the archive record untouched for provenance; render only translated text.
    title = _portuguese(recipe["title"])
    ingredients = [_portuguese(x) for x in recipe["ingredients"][:7]]
    instructions = [_portuguese(x) for x in recipe["steps"]]
    # Read every step for selected short recipes; never cut off an instruction mid-recipe.
    directions = instructions
    narration = f"Hoje fazemos {title}. Vai precisar de " + "; ".join(ingredients) + ". "
    narration += "Vamos a isso. " + " ".join(directions) + " "
    narration += "Receita histórica recuperada de um arquivo público. Guarde para experimentar e diga nos comentários o que mudaria."
    source = recipe.get("source_title") or recipe.get("collection") or "Arquivo de receitas"
    attribution = f"Fonte histórica: {source} ({recipe.get('source_year') or 'data não indicada'}). Autor: {recipe.get('author') or 'não indicado'}. Licença registada: {recipe.get('license')}. URL: {recipe.get('source_url') or 'sem URL indicado'}."
    desc = f"Uma receita antiga recuperada e adaptada para um Short. As instruções e ingredientes vêm da fonte identificada; podem refletir medidas e práticas da época. Confirme alergénios, temperaturas internas seguras e conservação antes de cozinhar.\n\n{attribution}\n\n#receitas #cozinha #shorts"
    scenes = [("A RECEITA DE HOJE", title), ("INGREDIENTES", "\n".join(f"• {item}" for item in ingredients))]
    for number, step in enumerate(directions, 1):
        scenes.append((f"PASSO {number}", step))
    scenes.append(("BOM APETITE", "Guarde esta receita • Qual é a próxima?"))
    yt_title = f"{title} | Receita antiga, sabor para hoje #Shorts"
    tags = ["receitas", "cozinha", "receitas portuguesas", "culinária", "shorts", "receita histórica"]
    return Short(recipe, yt_title[:100], narration, desc, tags, scenes)
