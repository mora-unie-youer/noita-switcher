"""Profile storage for Noita's save slots (``save00`` .. ``save06``).

Layout
------
* The **active** profile is the live contents of every ``saveNN`` directory (what the game
  reads and what Steam Auto-Cloud already syncs there).
* Every **inactive** profile is a single ``noita-switcher.<id>.tar.gz`` in the ``save00``
  root; archive members are paths relative to ``Nolla_Games_Noita`` (``save00/...``,
  ``save03/...``).
* ``noita-switcher.json`` (also in the ``save00`` root) records profile names and which one
  is active.
* ``save_shared`` (game config: video, audio, keys) is deliberately not part of a profile.

Noita's Auto-Cloud rules sync ``save00`` itself (``*``, non-recursive) plus a fixed set of its
sub-directories, and ``save01``..``save06`` recursively. Files in the ``save00`` root are
therefore synced, while any extra sub-directory would not be. Keeping profiles as root-level
archives is what lets them ride along in Steam Cloud.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import sys
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

STATE_FILE = "noita-switcher.json"
_PREFIX = "noita-switcher."
_ARCHIVE_SUFFIX = ".tar.gz"
_STEAM_MARKER = "steam_autocloud.vdf"
DEFAULT_PROFILE = "default"
MAX_NAME_LEN = 64


class ProfileError(Exception):
    pass


MODES = ("solo", "coop")
DEFAULT_MODE = "solo"


@dataclass
class Info:
    name: str
    active: bool
    created: float
    size: int | None  # uncompressed bytes of the profile's files; None if archive missing/unreadable
    mode: str


_SLOT_RE = re.compile(r"save\d\d")


def _is_protected(rel: str, home_slot: str) -> bool:
    """Files that are never archived, extracted over, or deleted by a switch."""
    parts = PurePosixPath(rel).parts
    return parts[-1] == _STEAM_MARKER or (len(parts) == 2 and parts[0] == home_slot and parts[1].startswith(_PREFIX))


def validate_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ProfileError("profile name must not be empty")
    if len(name) > MAX_NAME_LEN:
        raise ProfileError(f"profile name is longer than {MAX_NAME_LEN} characters")
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ProfileError("profile name must not contain control characters")
    return name


def _ancestor_pids() -> set[int]:
    """Own pid and all parents (Steam's wrapper/reaper carry noita.exe in their cmdline)."""
    pids = set()
    pid = os.getpid()
    while pid > 1 and pid not in pids:
        pids.add(pid)
        try:
            with open(f"/proc/{pid}/stat", "rb") as f:
                pid = int(f.read().rsplit(b")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return pids


def _looks_like_game(raw: bytes) -> bool:
    """True for the game or its launchers (proton, wine, pressure-vessel), not for tools that
    merely mention it: noita_proxy (its --launch-cmd contains noita.exe) and noita-switcher."""
    low = raw.replace(b"\0", b" ").decode(errors="replace").lower()
    if "noita.exe" not in low or "noita-switcher" in low or "noita_switcher" in low:
        return False
    argv0 = raw.split(b"\0", 1)[0].decode(errors="replace").replace("\\", "/").rsplit("/", 1)[-1].lower()
    return not argv0.startswith("noita_proxy")


def running_game_process(proc_root: str = "/proc", skip: set[int] | None = None) -> str | None:
    """Description of a process that looks like a running Noita, else None.

    ``skip``: pids to ignore; defaults to our own ancestors (Steam's wrapper/reaper carry
    noita.exe in their command line).
    """
    if sys.platform == "win32":
        import subprocess

        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq noita.exe", "/NH"], capture_output=True, text=True
        ).stdout
        return "noita.exe (tasklist)" if "noita.exe" in out.lower() else None
    skipped = {str(p) for p in (_ancestor_pids() if skip is None else skip)}
    try:
        pids = sorted(p for p in os.listdir(proc_root) if p.isdigit() and p not in skipped)
    except OSError:
        return None
    for pid in pids:
        try:
            with open(f"{proc_root}/{pid}/cmdline", "rb") as f:
                raw = f.read()
        except OSError:
            continue
        if _looks_like_game(raw):
            return f"pid {pid}: {raw.replace(chr(0).encode(), b' ').decode(errors='replace').strip()[:200]}"
    return None


class Store:
    def __init__(self, save_dir: Path):
        self.dir = Path(save_dir)
        self.adopted = False  # set when the first load created the state file

    # ---- state ---------------------------------------------------------

    @property
    def _state_path(self) -> Path:
        return self.dir / STATE_FILE

    def _load(self) -> dict:
        try:
            raw = self._state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            state = {
                "version": 1,
                "active": DEFAULT_PROFILE,
                "profiles": {
                    DEFAULT_PROFILE: {"id": self._new_id(), "created": time.time(), "mode": DEFAULT_MODE}
                },
                "pending": None,
            }
            self._save(state)
            self.adopted = True
            return state
        try:
            state = json.loads(raw)
            state["profiles"][state["active"]]
        except (ValueError, KeyError, TypeError) as e:
            raise ProfileError(f"{self._state_path} is corrupt: {e!r}") from e
        state.setdefault("pending", None)
        return state

    def _save(self, state: dict) -> None:
        self._atomic_write(self._state_path, json.dumps(state, ensure_ascii=False, indent=2).encode())

    def _atomic_write(self, dest: Path, data: bytes) -> None:
        tmp = self._tmp_path()
        try:
            tmp.write_bytes(data)
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)

    def _tmp_path(self) -> Path:
        return self.dir / f"{_PREFIX}tmp-{secrets.token_hex(4)}"

    def _new_id(self) -> str:
        return secrets.token_hex(4)

    def _archive(self, state: dict, name: str) -> Path:
        return self.dir / f"{_PREFIX}{state['profiles'][name]['id']}{_ARCHIVE_SUFFIX}"

    def _resolve(self, state: dict, name: str) -> str:
        wanted = name.strip().casefold()
        for existing in state["profiles"]:
            if existing.casefold() == wanted:
                return existing
        raise ProfileError(f"no such profile: {name!r}")

    def _require_clean(self, state: dict) -> None:
        if state["pending"]:
            p = state["pending"]
            raise ProfileError(
                f"an earlier switch {p['from']!r} -> {p['to']!r} was interrupted; "
                f"re-run `use <profile>` to finish it (save00 may be incomplete)"
            )

    def _require_game_closed(self, force: bool) -> None:
        proc = None if force else running_game_process()
        if proc:
            raise ProfileError(f"Noita seems to be running ({proc}); close it first (or pass --force)")

    # ---- live files ----------------------------------------------------

    @property
    def root(self) -> Path:
        return self.dir.parent

    def _slots(self) -> list[Path]:
        """save00 plus whichever save01..save06 the game has created."""
        slots = [self.dir]
        for p in sorted(self.root.iterdir()):
            if p != self.dir and _SLOT_RE.fullmatch(p.name) and p.is_dir() and not p.is_symlink():
                slots.append(p)
        return slots

    def _live_entries(self) -> list[tuple[str, Path, bool]]:
        """(posix path relative to the game root, absolute path, is_dir) for everything in a profile."""
        out = []
        for slot in self._slots():
            out.append((slot.name, slot, True))
            for dirpath, dirs, files in os.walk(slot):
                base = Path(dirpath)
                for d in dirs:
                    p = base / d
                    if not p.is_symlink():
                        out.append((p.relative_to(self.root).as_posix(), p, True))
                for f in files:
                    p = base / f
                    rel = p.relative_to(self.root).as_posix()
                    if p.is_file() and not p.is_symlink() and not _is_protected(rel, self.dir.name):
                        out.append((rel, p, False))
        return out

    def _live_size(self) -> int:
        return sum(p.stat().st_size for _rel, p, is_dir in self._live_entries() if not is_dir)

    @staticmethod
    def _archive_size(archive: Path) -> int | None:
        """Uncompressed bytes of the files in an archive, comparable to ``_live_size``."""
        if not archive.exists():
            return None
        try:
            with tarfile.open(archive, "r:gz") as tar:
                return sum(m.size for m in tar if m.isfile())
        except (tarfile.TarError, OSError, EOFError):
            return None

    def _write_archive(self, dest: Path) -> None:
        tmp = self._tmp_path()
        try:
            with tarfile.open(tmp, "w:gz") as tar:
                for rel, p, _is_dir in sorted(self._live_entries()):
                    tar.add(p, arcname=rel, recursive=False)
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)

    def _clear_live(self) -> None:
        entries = self._live_entries()
        for _rel, p, is_dir in entries:
            if not is_dir:
                p.unlink()
        # Drop the old profile's directory skeleton too (deepest first); the save00 root
        # stays, and dirs still holding protected files are left alone.
        for _rel, p, is_dir in sorted(entries, key=lambda e: e[0], reverse=True):
            if is_dir and p != self.dir:
                try:
                    p.rmdir()
                except OSError:
                    pass

    def _check_member(self, m: tarfile.TarInfo) -> str:
        rel = PurePosixPath(m.name)
        if rel.is_absolute() or ".." in rel.parts or not rel.parts or "\\" in m.name:
            raise ProfileError(f"unsafe path in archive: {m.name!r}")
        if rel.parts[0] != self.dir.name and not _SLOT_RE.fullmatch(rel.parts[0]):
            raise ProfileError(f"archive entry outside the save slots (old archive format?): {m.name!r}")
        if not (m.isfile() or m.isdir()):
            raise ProfileError(f"unsupported entry in archive: {m.name!r}")
        return rel.as_posix()

    def _validate_archive(self, archive: Path) -> None:
        try:
            with tarfile.open(archive, "r:gz") as tar:
                for m in tar:
                    self._check_member(m)
        except (tarfile.TarError, OSError, EOFError) as e:
            raise ProfileError(f"archive {archive.name} is unreadable: {e}") from e

    def _extract(self, archive: Path) -> None:
        # mtime = now: Steam Cloud resolves conflicts by timestamp, and a restored
        # old mtime could make it prefer the remote copy of the previous profile.
        now = time.time()
        with tarfile.open(archive, "r:gz") as tar:
            for m in tar:
                rel = self._check_member(m)
                dest = self.root / rel
                if m.isdir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                if _is_protected(rel, self.dir.name):
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                src = tar.extractfile(m)
                assert src is not None
                with src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
                os.chmod(dest, (m.mode & 0o777) | 0o600)
                os.utime(dest, (now, now))

    # ---- public API ----------------------------------------------------

    def active(self) -> str:
        return self._load()["active"]

    def mode(self, name: str) -> str:
        state = self._load()
        return state["profiles"][self._resolve(state, name)].get("mode", DEFAULT_MODE)

    def set_mode(self, name: str, mode: str) -> None:
        if mode not in MODES:
            raise ProfileError(f"mode must be one of: {', '.join(MODES)}")
        state = self._load()
        self._require_clean(state)
        state["profiles"][self._resolve(state, name)]["mode"] = mode
        self._save(state)

    def pending(self) -> dict | None:
        return self._load()["pending"]

    def list(self) -> list[Info]:
        state = self._load()
        infos = []
        for name, meta in state["profiles"].items():
            is_active = name == state["active"]
            if is_active:
                size = self._live_size()
            else:
                arch = self._archive(state, name)
                size = self._archive_size(arch)
            infos.append(Info(name, is_active, meta["created"], size, meta.get("mode", DEFAULT_MODE)))
        return infos

    def new(
        self, name: str, source: str | None = None, switch: bool = False, force: bool = False, mode: str = DEFAULT_MODE
    ) -> None:
        """Create a profile: empty, or a copy of ``source`` (a profile name)."""
        name = validate_name(name)
        state = self._load()
        self._require_clean(state)
        if any(n.casefold() == name.casefold() for n in state["profiles"]):
            raise ProfileError(f"profile {name!r} already exists")
        if mode not in MODES:
            raise ProfileError(f"mode must be one of: {', '.join(MODES)}")
        if switch:
            self._require_game_closed(force)  # fail before creating anything we cannot switch to
        meta = {"id": self._new_id(), "created": time.time(), "mode": mode}
        state["profiles"][name] = meta
        dest = self._archive(state, name)
        try:
            if source is None:
                with tarfile.open(dest, "w:gz"):
                    pass
            else:
                src = self._resolve(state, source)
                if src == state["active"]:
                    self._require_game_closed(force)
                    self._write_archive(dest)
                else:
                    src_arch = self._archive(state, src)
                    if not src_arch.exists():
                        raise ProfileError(f"archive for profile {src!r} is missing")
                    shutil.copyfile(src_arch, dest)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        self._save(state)
        if switch:
            self.switch(name, force=force)

    def switch(self, name: str, force: bool = False) -> bool:
        """Make ``name`` active. Returns False if it already was."""
        state = self._load()
        target = self._resolve(state, name)
        pending = state["pending"]
        if not pending and target == state["active"]:
            return False
        self._require_game_closed(force)

        target_archive = self._archive(state, target)
        if not target_archive.exists():
            raise ProfileError(f"archive for profile {target!r} is missing; cannot switch")
        self._validate_archive(target_archive)

        if not pending:
            # Park the current profile first; only then touch the live files.
            self._write_archive(self._archive(state, state["active"]))
            state["pending"] = {"from": state["active"], "to": target}
            self._save(state)

        self._clear_live()
        self._extract(target_archive)

        state["active"] = target
        state["pending"] = None
        self._save(state)
        target_archive.unlink(missing_ok=True)  # live files are now the source of truth
        return True

    def rename(self, old: str, new: str) -> None:
        new = validate_name(new)
        state = self._load()
        self._require_clean(state)
        old = self._resolve(state, old)
        if new.casefold() != old.casefold() and any(n.casefold() == new.casefold() for n in state["profiles"]):
            raise ProfileError(f"profile {new!r} already exists")
        profiles = {(new if n == old else n): m for n, m in state["profiles"].items()}
        state["profiles"] = profiles
        if state["active"] == old:
            state["active"] = new
        self._save(state)

    def delete(self, name: str) -> None:
        state = self._load()
        self._require_clean(state)
        name = self._resolve(state, name)
        if name == state["active"]:
            raise ProfileError(f"{name!r} is the active profile; switch to another one first")
        self._archive(state, name).unlink(missing_ok=True)
        del state["profiles"][name]
        self._save(state)
