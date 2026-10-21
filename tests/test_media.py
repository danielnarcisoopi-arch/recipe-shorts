import json
from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from recipe_shorts import media
from recipe_shorts.media import _metadata_text, _find_commons_image, render_scene, verify_shorts_format


def test_commons_license_metadata_html_is_normalized():
    assert _metadata_text('<a href="/wiki/CC_BY-SA_4.0">CC BY-SA 4.0</a>') == "CC BY-SA 4.0"


def test_missing_photo_still_renders_honest_photo_unavailable_card(tmp_path):
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


def test_final_scene_shows_the_finished_dish_photo(tmp_path):
    photo = tmp_path / "finished-dish.jpg"
    Image.new("RGB", (640, 480), (190, 35, 45)).save(photo)
    output = tmp_path / "final-scene.jpg"
    render_scene("O PRATO FINAL", "Bom apetite!", photo, 3, 4, output, ["ovos", "tomate"])
    with Image.open(output) as frame:
        r, g, b = frame.getpixel((540, 630))
        assert r > 150 and g < 80 and b < 80


def test_commons_search_downloads_a_real_open_licensed_photo(monkeypatch, tmp_path):
    buffer = BytesIO()
    Image.new("RGB", (640, 480), (60, 145, 75)).save(buffer, format="JPEG")
    image_bytes = buffer.getvalue()

    class Response:
        def __init__(self, payload=None, content=b"", headers=None):
            self.payload, self.content, self.headers = payload, content, headers or {}

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    responses = [
        Response({"query": {"search": [{"title": "File:Eggs.jpg"}]}}),
        Response({"query": {"pages": [{"title": "File:Eggs.jpg", "imageinfo": [{
            "thumburl": "https://upload.wikimedia.org/eggs.jpg",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Eggs.jpg",
            "extmetadata": {"LicenseShortName": {"value": "<a>CC BY-SA 4.0</a>"},
                             "Artist": {"value": "Test Photographer"}},
        }]}]}}),
        Response(content=image_bytes, headers={"Content-Type": "image/jpeg"}),
    ]
    monkeypatch.setattr(media.requests, "get", lambda *args, **kwargs: responses.pop(0))
    path, credit = _find_commons_image(["eggs food"], tmp_path / "eggs.jpg", (500, 350))
    assert path is not None and path.exists()
    assert "CC BY-SA 4.0" in credit
    with Image.open(path) as downloaded:
        assert downloaded.size == (640, 480)


def test_ingredient_search_uses_english_term_and_returns_photo(monkeypatch, tmp_path):
    buffer = BytesIO()
    Image.new("RGB", (640, 480), (210, 170, 90)).save(buffer, format="JPEG")
    image_bytes = buffer.getvalue()

    class Response:
        def __init__(self, payload=None, content=b"", headers=None):
            self.payload, self.content, self.headers = payload, content, headers or {}

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    responses = [
        Response([[['eggs', 'ovos', None, None]]]),
        Response({"query": {"search": [{"title": "File:Eggs.jpg"}]}}),
        Response({"query": {"pages": [{"title": "File:Eggs.jpg", "imageinfo": [{
            "thumburl": "https://upload.wikimedia.org/eggs.jpg",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Eggs.jpg",
            "extmetadata": {"LicenseShortName": {"value": "CC0"}, "Artist": {"value": "Archive"}},
        }]}]}}),
        Response(content=image_bytes, headers={"Content-Type": "image/jpeg"}),
    ]
    monkeypatch.setattr(media.requests, "get", lambda *args, **kwargs: responses.pop(0))
    photos, credits = media.get_ingredient_images(["2 ovos"], tmp_path)
    assert "2 ovos" in photos and photos["2 ovos"].is_file()
    assert len(credits) == 1 and "CC0" in credits[0]


def test_food_photo_relevance_rejects_people_and_accepts_the_ingredient_itself():
    assert not media._food_photo_relevant("milk", "A child drinking a glass of milk")
    assert media._food_photo_relevant("milk", "A glass bottle filled with milk")


def test_pexels_skips_lifestyle_result_and_downloads_actual_ingredient(monkeypatch, tmp_path):
    buffer = BytesIO()
    Image.new("RGB", (640, 480), (240, 240, 235)).save(buffer, format="JPEG")
    image_bytes = buffer.getvalue()

    class Response:
        def __init__(self, payload=None, content=b"", headers=None):
            self.payload, self.content, self.headers = payload, content, headers or {}

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if url.endswith("/search"):
            return Response({"photos": [
                {"width": 640, "height": 480, "alt": "A child drinking milk", "src": {"large": "https://images.pexels.com/child.jpg"}},
                {"width": 640, "height": 480, "alt": "A glass bottle filled with milk", "src": {"large": "https://images.pexels.com/milk.jpg"},
                 "photographer": "Test Photographer", "url": "https://www.pexels.com/photo/milk/"},
            ]})
        return Response(content=image_bytes, headers={"Content-Type": "image/jpeg"})

    monkeypatch.setenv("PEXELS_API_KEY", "test-key")
    monkeypatch.setattr(media.requests, "get", fake_get)
    path, credit = media._find_pexels_image(["milk"], tmp_path / "milk.jpg", (500, 350))
    assert path is not None and path.exists()
    assert "Test Photographer" in credit
    assert calls[-1].endswith("milk.jpg")


def test_short_preflight_accepts_vertical_video_and_rejects_landscape(monkeypatch, tmp_path):
    probes = [
        {"streams": [{"codec_type": "video", "width": 1080, "height": 1920}], "format": {"duration": "45.0"}},
        {"streams": [{"codec_type": "video", "width": 1920, "height": 1080}], "format": {"duration": "45.0"}},
    ]
    monkeypatch.setattr(media.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(probes.pop(0))))
    assert verify_shorts_format(tmp_path / "vertical.mp4")["height"] == 1920
    import pytest
    with pytest.raises(RuntimeError, match="vertical ou quadrado"):
        verify_shorts_format(tmp_path / "landscape.mp4")
