from recipe_shorts.content import build_short
from recipe_shorts.library import _is_portuguese, _sections


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


def test_portuguese_recipe_headings_and_language_gate():
    body = """## Ingredientes
- 2 ovos
- 1 chávena de leite
- 200 g de farinha

## Modo de preparação
1. Misture os ingredientes numa tigela e bata bem até obter uma massa lisa.
2. Aqueça uma frigideira e cozinhe pequenas porções dos dois lados.
"""
    ingredients, steps = _sections(body)
    recipe = {"title": "Panquecas", "ingredients": ingredients, "steps": steps}
    assert len(ingredients) == 3
    assert len(steps) == 2
    assert _is_portuguese(recipe)
    english = {"title": "Pancakes", "ingredients": ["2 eggs", "milk", "flour"],
               "steps": ["Mix the ingredients in a bowl until smooth.", "Cook in a hot pan on both sides."]}
    assert not _is_portuguese(english)


def test_short_ends_with_final_dish_scene():
    recipe = {"id": "x", "title": "Panquecas", "source_title": "Livro de Cozinha",
              "source_year": "1900", "source_url": "https://example.test", "license": "public-domain",
              "ingredients": ["2 ovos", "leite", "farinha"],
              "steps": ["Misture os ingredientes muito bem numa tigela."]}
    short = build_short(recipe)
    assert short.scenes[1][0] == "INGREDIENTES"
    assert short.scenes[-1] == ("PRATO FINAL", "Panquecas")
