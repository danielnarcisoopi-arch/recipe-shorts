import json
from pathlib import Path

from recipe_shorts.youtube import authenticated_channel

path = Path("token-recipes.json")
if not path.exists():
    raise SystemExit("token-recipes.json não existe; execute scripts/auth_youtube.py")
channel_id, name = authenticated_channel(path.read_text(encoding="utf-8"))
print(json.dumps({"channel_name": name, "channel_id": channel_id}, ensure_ascii=False, indent=2))
