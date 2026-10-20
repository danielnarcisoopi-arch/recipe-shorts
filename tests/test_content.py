from recipe_shorts.content import build_short
from recipe_shorts.library import _sections


def test_parse_markdown_ingredients_and_steps():
    body = """## Ingredients
- 2 ovos
- 1 chávena de leite
- 200 g de farinha

## Directions
1. Misture os ingredientes numa tigela até obter uma massa lisa.
2. Aqueça uma frigideira e cozinhe pequenas porções dos dois lados.
"""
    ingredients, steps = _sections(body)
    assert ingredients == ["2 ovos", "1 chávena de leite", "200 g de farinha"]
    assert len(steps) == 2


def test_short_keeps_source_and_recipe_facts():
    recipe = {"id": "x", "title": "Panquecas", "collection": "Portugal", "culture": "portugal",
              "author": "A. Example", "source_title": "Livro de Cozinha", "source_url": "https://example.test",
              "source_year": "1900", "license": "public-domain", "ingredients": ["2 ovos", "leite", "farinha"],
              "steps": ["Misture os ingredientes muito bem numa tigela.", "Cozinhe a massa numa frigideira quente."]}
    short = build_short(recipe)
    assert "2 ovos" in short.narration
    assert "Livro de Cozinha" in short.description
    assert len(short.scenes) >= 4
    assert "#Shorts" in short.title


def test_no_sections_are_invented():
    ingredients, steps = _sections("A short paragraph with no structured recipe content.")
    assert ingredients == []
    assert steps == []
