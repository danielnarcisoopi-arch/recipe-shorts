from __future__ import annotations

import re
from dataclasses import dataclass


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


def build_short(recipe: dict) -> Short:
    title = _plain(recipe["title"])
    ingredients = [_plain(x) for x in recipe["ingredients"][:7]]
    instructions = [_plain(x) for x in recipe["steps"]]
    # Read every step for selected short recipes; never cut off an instruction mid-recipe.
    directions = instructions
    narration = f"Hoje, vamos preparar {title}. "
    narration += "Para esta receita, precisa de: " + ". ".join(ingredients) + ". "
    narration += "Agora, siga estes passos. " + " ".join(directions) + " "
    narration += "E está pronto. Receita de arquivo, adaptada para a sua cozinha. Guarde este vídeo e diga-me nos comentários se vai experimentar."
    source = recipe.get("source_title") or recipe.get("collection") or "Arquivo de receitas"
    attribution = f"Fonte histórica: {source} ({recipe.get('source_year') or 'data não indicada'}). Autor: {recipe.get('author') or 'não indicado'}. Licença registada: {recipe.get('license')}. URL: {recipe.get('source_url') or 'sem URL indicado'}."
    desc = f"Uma receita antiga recuperada e adaptada para um Short. As instruções e ingredientes vêm da fonte identificada; podem refletir medidas e práticas da época. Confirme alergénios, temperaturas internas seguras e conservação antes de cozinhar.\n\n{attribution}\n\n#receitas #cozinha #shorts"
    scenes = [("A RECEITA DE HOJE", title), ("INGREDIENTES", " · ".join(ingredients))]
    for number, step in enumerate(directions, 1):
        scenes.append((f"PASSO {number}", step))
    scenes.append(("PRATO FINAL", title))
    yt_title = f"{title} | Receita em português #Shorts"
    tags = ["receitas", "cozinha", "receitas portuguesas", "culinária", "shorts"]
    return Short(recipe, yt_title[:100], narration, desc, tags, scenes)
