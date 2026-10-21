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


def test_short_keeps_source_and_recipe_facts(monkeypatch):
    monkeypatch.setattr("recipe_shorts.content._portuguese", lambda value: value)
    recipe = {"id": "x", "title": "Panquecas", "collection": "Portugal", "culture": "portugal",
              "author": "A. Example", "source_title": "Livro de Cozinha", "source_url": "https://example.test",
              "source_year": "1900", "license": "public-domain", "ingredients": ["2 ovos", "leite", "farinha"],
              "steps": ["Misture os ingredientes muito bem numa tigela.", "Cozinhe a massa numa frigideira quente."]}
    short = build_short(recipe)
    assert "2 ovos" in short.narration
    assert "Livro de Cozinha" in short.description
    assert len(short.scenes) >= 4
    assert "#Shorts" in short.title


def test_every_recipe_field_is_translated_before_rendering(monkeypatch):
    translations = {
        "Pancakes": "Panquecas", "2 eggs": "2 ovos", "milk": "leite", "flour": "farinha",
        "Mix the ingredients well in a bowl.": "Misture bem os ingredientes numa tigela.",
        "Cook the batter in a hot pan.": "Cozinhe a massa numa frigideira quente.",
    }
    monkeypatch.setattr("recipe_shorts.content._portuguese", lambda value: translations[value])
    recipe = {"id": "x", "title": "Pancakes", "collection": "Portugal", "source_title": "Recipe book",
              "ingredients": ["2 eggs", "milk", "flour"],
              "steps": ["Mix the ingredients well in a bowl.", "Cook the batter in a hot pan."]}
    short = build_short(recipe)
    assert "Panquecas" in short.narration
    assert "2 ovos" in short.narration
    assert "farinha" in short.narration
    assert "frigideira" in short.narration
    assert "Pancakes" not in short.narration
    assert "• 2 ovos" in short.scenes[1][1]


def test_translation_targets_european_portuguese_without_network(monkeypatch):
    from recipe_shorts import content

    class Response:
        def raise_for_status(self):
            pass

        @staticmethod
        def json():
            return [[['Asse até dourar.', 'Bake until golden.', None, None]]]

    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    content._translation_cache.clear()
    monkeypatch.setattr(content.requests, "get", fake_get)
    assert content._portuguese("Bake until golden.") == "Asse até dourar."
    assert calls[0][1]["params"]["tl"] == "pt-PT"


def test_no_sections_are_invented():
    ingredients, steps = _sections("A short paragraph with no structured recipe content.")
    assert ingredients == []
    assert steps == []
