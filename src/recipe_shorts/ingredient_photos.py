"""Ingredient photographs selected from Commons file descriptions, checked 2026-10-21.

Match complete ingredient names, never a substring: coconut milk must not match milk.
Each source page records the photographer, license and the actual food pictured.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote


def _photo(names, filename, path, author, license_name, license_url):
    return {
        "names": names,
        "url": f"https://upload.wikimedia.org/wikipedia/commons/{path}/{quote(filename)}",
        "page": f"https://commons.wikimedia.org/wiki/File:{quote(filename)}",
        "author": author, "license": license_name, "license_url": license_url,
    }


PHOTOS = (
    _photo(("leite", "leite gordo", "leite meio gordo", "milk", "whole milk"),
           "Milk_glass.jpg", "0/0e", "Stefan Kühn", "CC BY-SA 3.0",
           "https://creativecommons.org/licenses/by-sa/3.0/"),
    _photo(("ovo", "ovos", "egg", "eggs", "ovos grandes", "large eggs"),
           "Chicken_eggs.jpg", "0/0e", "Fir0002", "CC BY-SA 3.0",
           "https://creativecommons.org/licenses/by-sa/3.0/"),
    _photo(("farinha", "farinha trigo", "farinha de trigo", "flour", "wheat flour", "all purpose flour"),
           "Mixing_Bowl_of_Flour.JPG", "3/33", "ParentingPatch", "CC BY-SA 3.0",
           "https://creativecommons.org/licenses/by-sa/3.0/"),
    _photo(("acucar", "acucar branco", "sugar", "white sugar", "granulated sugar"),
           "Sugar_bowl.png", "d/d4", "Jen.wright", "CC BY-SA 4.0",
           "https://creativecommons.org/licenses/by-sa/4.0/"),
    _photo(("manteiga", "butter", "unsalted butter", "manteiga sem sal", "salted butter"),
           "Butter_with_a_butter_knife.jpg", "b/b5", "Carey Tilden", "CC BY 2.0",
           "https://creativecommons.org/licenses/by/2.0/"),
    _photo(("azeite", "azeite virgem extra", "olive oil", "extra virgin olive oil"),
           "OliveOil.png", "a/a9", "Itineranttrader", "Public domain",
           "https://commons.wikimedia.org/wiki/File:OliveOil.png#Licensing"),
    _photo(("canela em pau", "pau canela", "paus canela", "cinnamon stick", "cinnamon sticks"),
           "Cinnamon.jpg", "6/63", "Thamizhpparithi Maari", "CC BY-SA 4.0",
           "https://creativecommons.org/licenses/by-sa/4.0/"),
    _photo(("limao", "limoes", "lemon", "lemons"),
           "Lemon_-_whole_and_split.jpg", "f/f7", "Ivar Leidus", "CC BY-SA 4.0",
           "https://creativecommons.org/licenses/by-sa/4.0/"),
    _photo(("sal", "sal fino", "sal grosso", "salt", "sea salt", "table salt"),
           "Salt_-_close-up.jpg", "2/28", "André Karwath (Aka)", "CC BY-SA 2.5",
           "https://creativecommons.org/licenses/by-sa/2.5/"),
)


def _name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower()).encode("ascii", "ignore").decode()
    value = re.sub(r"\bq\.?\s*b\.?", " ", value)
    value = re.sub(r"\b\d+(?:[.,/]\d+)?\b", " ", value)
    value = re.sub(r"\b(?:g|kg|mg|ml|cl|l|dl|oz|lb|cups?|tablespoons?|teaspoons?|tbsp|tsp|colheres?|colherinhas?|chavenas?|xicaras?|sopa|cha|pitada|pitadas|de|da|do|das|dos)\b", " ", value)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", value)).strip()


_BY_NAME = {_name(alias): photo for photo in PHOTOS for alias in photo["names"]}


def ingredient_photo(value: str) -> dict | None:
    return _BY_NAME.get(_name(value))
