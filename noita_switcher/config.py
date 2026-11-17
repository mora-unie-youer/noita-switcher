"""Per-machine settings (paths differ between machines, so they are NOT stored in save00)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "noita-switcher" / "config.json"


def load() -> dict:
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError as e:
        raise ValueError(f"{config_path()} is corrupt: {e}") from e


def save(cfg: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def log_path() -> Path:
    if sys.platform == "win32":
        return config_path().with_name("launch.log")
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    return base / "noita-switcher" / "launch.log"


def log(message: str) -> None:
    """Append to the launch log. Steam launches have no visible stderr, so this is the only trace."""
    import time

    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 256 * 1024:
            path.write_text("")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass
