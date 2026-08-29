import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "config"
PROFILE_PATH = CONFIG_DIR / "profile.json"


def load_profile() -> dict:
    if not PROFILE_PATH.exists():
        raise RuntimeError(
            f"{PROFILE_PATH} not found. Copy config/profile.example.json to "
            "config/profile.json and fill in real values."
        )
    return json.loads(PROFILE_PATH.read_text())
