"""Steam launch-option wrapper: pick a profile, switch to it, then start solo or co-op.

Steam launch option (Noita):  ``noita-switcher launch -- %command%``

Steam expands ``%command%`` to the full Proton command line. For a *solo* profile it is exec'd
unchanged. For a *coop* profile ``noita_proxy`` is exec'd instead, with that same command line
as ``--launch-cmd`` so the proxy's "Start game" button runs Noita exactly as Steam would
(this is what a manual ``./noita_proxy --launch-cmd "%command%"`` launch option does).
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from . import config
from .locate import steam_libraries
from .profiles import Info, ProfileError, Store

PROXY_ENV = "NOITA_PROXY"
_PROXY_NAMES = ("noita_proxy.exe",) if sys.platform == "win32" else ("noita_proxy", "noita_proxy.x86_64")


def _install_dirs() -> list[Path]:
    dirs = [Path.cwd()]
    if os.environ.get("STEAM_COMPAT_INSTALL_PATH"):
        dirs.append(Path(os.environ["STEAM_COMPAT_INSTALL_PATH"]))
    dirs += [lib / "steamapps/common/Noita" for lib in steam_libraries()]
    return [d for d in dirs if (d / "noita.exe").is_file()]


def find_proxy(override: str | None = None) -> tuple[Path, str] | None:
    """Returns (path, where-it-came-from). Explicit settings win; otherwise the newest proxy binary
    next to noita.exe (the proxy updates itself in place and may leave an older copy behind)."""
    for src, value in (("--proxy", override), (f"${PROXY_ENV}", os.environ.get(PROXY_ENV)), ("config", config.load().get("proxy"))):
        if value:
            path = Path(value).expanduser()
            if not path.is_file():
                raise ProfileError(f"noita_proxy from {src} does not exist: {path}")
            return path, src
    for d in _install_dirs():
        found = [d / n for n in _PROXY_NAMES if (d / n).is_file()]
        if found:
            return max(found, key=lambda p: p.stat().st_mtime), "auto"
    return None


# ---- profile chooser --------------------------------------------------------------------------


def _clean_env() -> dict[str, str]:
    # Steam's overlay preload has no business inside a dialog helper.
    env = dict(os.environ)
    env.pop("LD_PRELOAD", None)
    return env


def _has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _label(i: Info) -> str:
    return f"{i.name}  [{i.mode}]"


def _zenity(infos: Sequence[Info]) -> str | None:
    cmd = [
        "zenity", "--list", "--radiolist", "--title=noita-switcher", "--text=Choose a profile",
        "--column=", "--column=Profile", "--column=Mode", "--print-column=2",
        "--width=420", "--height=360",
    ]  # fmt: skip
    for i in infos:
        cmd += ["TRUE" if i.active else "FALSE", i.name, i.mode]
    r = subprocess.run(cmd, capture_output=True, text=True, env=_clean_env())
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def _kdialog(infos: Sequence[Info]) -> str | None:
    cmd = ["kdialog", "--title", "noita-switcher", "--radiolist", "Choose a profile"]
    for i in infos:
        cmd += [i.name, _label(i), "on" if i.active else "off"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=_clean_env())
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def _terminal(infos: Sequence[Info]) -> str | None:
    for n, i in enumerate(infos, 1):
        print(f"{'*' if i.active else ' '} {n}. {_label(i)}", file=sys.stderr)
    default = next((n for n, i in enumerate(infos, 1) if i.active), 1)
    while True:
        try:
            raw = input(f"Profile [{default}] (empty line = default, q = cancel): ").strip()
        except EOFError:
            return None
        if raw.lower() in ("q", "quit"):
            return None
        if not raw:
            return infos[default - 1].name
        if raw.isdigit() and 1 <= int(raw) <= len(infos):
            return infos[int(raw) - 1].name
        print("invalid choice", file=sys.stderr)


def choose_profile(infos: Sequence[Info]) -> str | None:
    """Ask the user. None = cancelled. With no way to ask, keep the active profile."""
    if _has_display():
        if shutil.which("zenity"):
            return _zenity(infos)
        if shutil.which("kdialog"):
            return _kdialog(infos)
    if sys.stdin.isatty():
        return _terminal(infos)
    active = next((i.name for i in infos if i.active), None)
    print("no dialog tool (zenity/kdialog) or terminal; keeping the active profile", file=sys.stderr)
    return active


def show_error(message: str) -> None:
    """Best-effort GUI error; Steam launches have no terminal to read stderr from."""
    if sys.stderr.isatty() or not _has_display():
        return
    for cmd in (["zenity", "--error", "--title=noita-switcher", f"--text={message}"],
                ["kdialog", "--title", "noita-switcher", "--error", message]):  # fmt: skip
        if shutil.which(cmd[0]):
            subprocess.run(cmd, env=_clean_env(), capture_output=True)
            return


# ---- launch -----------------------------------------------------------------------------------


def launch(
    store: Store,
    command: Sequence[str],
    profile: str | None = None,
    *,
    force: bool = False,
    proxy: str | None = None,
    choose: Callable[[Sequence[Info]], str | None] = choose_profile,
    execvp: Callable[[str, list[str]], None] = os.execvp,
) -> int:
    command = list(command)
    config.log(f"launch: pid={os.getpid()} profile={profile!r} cmd={shlex.join(command)[:300]}")
    if command[:1] == ["--"]:
        command = command[1:]

    if profile is None:
        profile = choose(store.list())
        if profile is None:
            print("cancelled", file=sys.stderr)
            return 0

    mode = store.mode(profile)  # also validates the name
    proxy_path = None
    if mode == "coop":
        found = find_proxy(proxy)
        if not found:
            raise ProfileError("noita_proxy not found next to noita.exe; point to it with `noita-switcher proxy PATH`")
        proxy_path = found[0]
    elif not command:
        raise ProfileError("no game command; use it as a Steam launch option: noita-switcher launch -- %command%")

    # Resolve everything that can fail first: the switch below is the only destructive step.
    store.switch(profile, force=force)
    print(f"profile {store.active()!r} ({mode})", file=sys.stderr)
    config.log(f"switched to {store.active()!r} ({mode})")

    if proxy_path is not None:
        argv = [str(proxy_path)]
        if command:
            argv += ["--launch-cmd", shlex.join(command)]
        os.chdir(proxy_path.parent)
        execvp(argv[0], argv)
    else:
        execvp(command[0], command)
    return 0
