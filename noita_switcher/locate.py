"""Locate Noita's ``save00`` directory.

Noita is a Windows game; on Linux it runs under Proton, so the save lives in the
Wine prefix of the Steam library that holds the game's ``compatdata``. That
library may be on any mounted drive, so every library listed in
``libraryfolders.vdf`` is checked.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

APP_ID = "881100"
ENV_VAR = "NOITA_SAVE_DIR"
_GAME_DIRS = ("Nolla_Games_Noita", "save00")


def _steam_roots() -> list[Path]:
    home = Path.home()
    roots = [
        home / ".local/share/Steam",
        home / ".steam/steam",
        home / ".steam/root",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
        home / "snap/steam/common/.local/share/Steam",
    ]
    return [r for r in roots if r.is_dir()]


def _library_paths(steam_root: Path) -> list[Path]:
    libs = [steam_root]
    for vdf in (steam_root / "steamapps/libraryfolders.vdf", steam_root / "config/libraryfolders.vdf"):
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in re.findall(r'"path"\s+"([^"]*)"', text):
            libs.append(Path(raw.replace("\\\\", "\\")))
    return libs


def steam_libraries() -> list[Path]:
    """Every Steam library folder (deduplicated), across all Steam installs."""
    seen: set[Path] = set()
    out: list[Path] = []
    for root in _steam_roots():
        for lib in _library_paths(root):
            try:
                real = lib.resolve()
            except OSError:
                continue
            if real not in seen:
                seen.add(real)
                out.append(lib)
    return out


def _proton_candidates() -> list[Path]:
    prefix = Path("steamapps/compatdata") / APP_ID / "pfx/drive_c/users/steamuser/AppData/LocalLow"
    return [lib / prefix.joinpath(*_GAME_DIRS) for lib in steam_libraries()]


def _windows_candidates() -> list[Path]:
    bases = []
    if os.environ.get("LOCALAPPDATA"):
        bases.append(Path(os.environ["LOCALAPPDATA"]).parent / "LocalLow")
    if os.environ.get("USERPROFILE"):
        bases.append(Path(os.environ["USERPROFILE"]) / "AppData/LocalLow")
    return [b.joinpath(*_GAME_DIRS) for b in bases]


def _newest_mtime(path: Path) -> float:
    newest = path.stat().st_mtime
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                newest = max(newest, os.lstat(os.path.join(dirpath, f)).st_mtime)
            except OSError:
                pass
    return newest


def find_candidates() -> list[Path]:
    """All existing save00 directories, most recently modified first."""
    cands = _windows_candidates() if sys.platform == "win32" else _proton_candidates()
    found = [c for c in cands if c.is_dir()]
    found.sort(key=_newest_mtime, reverse=True)
    return found


def find_save_dir(override: str | os.PathLike[str] | None = None) -> Path:
    explicit = override or os.environ.get(ENV_VAR)
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_dir():
            raise FileNotFoundError(f"save directory does not exist: {path}")
        return path
    found = find_candidates()
    if not found:
        raise FileNotFoundError(
            "Noita save00 directory not found. Launch the game once so it creates the "
            f"save, or point to it with --dir / ${ENV_VAR}."
        )
    return found[0]
