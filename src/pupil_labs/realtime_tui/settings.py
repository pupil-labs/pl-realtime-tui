import json
import logging
import pathlib
from typing import Any

from platformdirs import user_config_dir

APP_NAME = "pl-realtime-tui"
APP_AUTHOR = "pupil-labs"

logger: logging.Logger = logging.getLogger(__name__)


def get_config_path() -> pathlib.Path:
    config_dir = pathlib.Path(user_config_dir(APP_NAME, APP_AUTHOR))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"


def save_settings(
    event_map: dict[str, str],
    sync_interval: float = 300.0,
    status_interval: float = 10.0,
    persist: bool = False,
) -> None:
    config_path: pathlib.Path = get_config_path()
    try:
        data: dict[str, Any] = {"persist": persist}
        if persist:
            data.update({
                "event_map": event_map,
                "sync_interval": sync_interval,
                "status_interval": status_interval,
            })

        with open(config_path, "w") as f:
            json.dump(data, f, indent=4)
    except Exception:
        logging.exception("Failed to save settings.")


def load_settings() -> dict[str, Any] | None:
    config_path: pathlib.Path = get_config_path()
    if not config_path.exists():
        return None
    try:
        with open(config_path) as f:
            data: Any = json.load(f)
            if isinstance(data, dict):
                return data
            return None
    except Exception:
        logging.exception("Failed to load settings.")
        return None
