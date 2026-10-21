from PIL import Image

from recipe_shorts.media import _metadata_text, render_scene


def test_commons_license_metadata_html_is_normalized():
    assert _metadata_text('<a href="/wiki/CC_BY-SA_4.0">CC BY-SA 4.0</a>') == "CC BY-SA 4.0"


def test_missing_photo_still_renders_ingredient_illustration(tmp_path):
    output = tmp_path / "ingredients.jpg"
    render_scene(
        "INGREDIENTES",
        "• 2 ovos\n• 200 g de farinha\n• 1 chávena de leite",
        None,
        1,
        5,
        output,
        ["2 ovos", "200 g de farinha", "1 chávena de leite"],
    )
    with Image.open(output) as frame:
        assert frame.size == (1080, 1920)
        assert frame.getpixel((500, 500)) != frame.getpixel((20, 20))
