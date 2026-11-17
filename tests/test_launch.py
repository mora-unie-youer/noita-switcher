import subprocess
import sys
from pathlib import Path

import pytest

from noita_switcher import profiles
from noita_switcher.launch import PROXY_ENV, find_proxy, launch
from noita_switcher.profiles import ProfileError, Store
from noita_switcher.profiles import running_game_process as scan_processes  # the autouse fixture patches the module attr

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def game_closed(monkeypatch):
    monkeypatch.setattr(profiles, "running_game_process", lambda: None)
    monkeypatch.delenv(PROXY_ENV, raising=False)


@pytest.fixture
def store(tmp_path):
    d = tmp_path / "save00"
    d.mkdir()
    (d / "mod_config.xml").write_text("solo-mods")
    s = Store(d)
    s.new("duo", mode="coop")
    return s


@pytest.fixture
def proxy(tmp_path, monkeypatch):
    p = tmp_path / "noita_proxy"
    p.write_text("#!/bin/sh\n")
    p.chmod(0o755)
    monkeypatch.setenv(PROXY_ENV, str(p))
    return p


GAME = ["/steam/reaper", "SteamLaunch", "--", "/p/proton", "waitforexitandrun", "/g/My Games/noita.exe"]


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, file, argv):
        self.calls.append((file, argv))


def test_solo_switches_then_execs_the_steam_command_unchanged(store):
    store.switch("duo")
    rec = Recorder()
    launch(store, ["--", *GAME], "default", execvp=rec)
    assert store.active() == "default"
    assert rec.calls == [(GAME[0], GAME)]
    assert (store.dir / "mod_config.xml").read_text() == "solo-mods"


def test_coop_switches_then_execs_proxy_with_full_command_as_launch_cmd(store, proxy, monkeypatch):
    monkeypatch.chdir(store.dir)
    rec = Recorder()
    launch(store, GAME, "duo", execvp=rec)
    assert store.active() == "duo"
    ((file, argv),) = rec.calls
    assert file == str(proxy)
    assert argv[:2] == [str(proxy), "--launch-cmd"]
    import shlex

    assert shlex.split(argv[2]) == GAME  # round-trips through the proxy's shlex::split, incl. the space in the path
    assert Path.cwd() == proxy.parent


def test_coop_without_proxy_fails_before_touching_the_save(store, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STEAM_COMPAT_INSTALL_PATH", str(tmp_path))
    monkeypatch.setattr("noita_switcher.launch.steam_libraries", lambda: [])
    rec = Recorder()
    with pytest.raises(ProfileError, match="noita_proxy not found"):
        launch(store, GAME, "duo", execvp=rec)
    assert store.active() == "default"
    assert (store.dir / "mod_config.xml").read_text() == "solo-mods"
    assert rec.calls == []


def test_cancelled_dialog_does_nothing(store, proxy):
    rec = Recorder()
    assert launch(store, GAME, None, choose=lambda infos: None, execvp=rec) == 0
    assert rec.calls == []
    assert store.active() == "default"


def test_dialog_receives_profiles_with_modes_and_active_flag(store, proxy):
    seen = []

    def choose(infos):
        seen.extend((i.name, i.mode, i.active) for i in infos)
        return "duo"

    rec = Recorder()
    launch(store, GAME, None, choose=choose, execvp=rec)
    assert seen == [("default", "solo", True), ("duo", "coop", False)]
    assert rec.calls[0][0] == str(proxy)


def test_solo_without_command_is_an_error(store):
    with pytest.raises(ProfileError, match="no game command"):
        launch(store, [], "default", execvp=Recorder())


def test_proxy_autodetect_prefers_newest_binary_next_to_noita_exe(tmp_path, monkeypatch):
    install = tmp_path / "Noita"
    install.mkdir()
    (install / "noita.exe").write_text("")
    old, new = install / "noita_proxy.x86_64", install / "noita_proxy"
    old.write_text("")
    new.write_text("")
    import os

    os.utime(old, (1, 1))
    monkeypatch.chdir(install)
    assert find_proxy() == (new, "auto")


def test_mode_defaults_to_solo_for_state_written_before_modes_existed(store):
    import json

    state = json.loads((store.dir / "noita-switcher.json").read_text())
    for meta in state["profiles"].values():
        del meta["mode"]
    (store.dir / "noita-switcher.json").write_text(json.dumps(state))
    assert {i.name: i.mode for i in store.list()} == {"default": "solo", "duo": "solo"}


def _fake_proc(root, procs):
    for pid, argv in procs.items():
        d = root / str(pid)
        d.mkdir(parents=True)
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")


def test_game_check_finds_the_game_but_not_steam_wrappers_proxy_or_switcher(tmp_path):
    steam_cmd = ["/steam/reaper", "SteamLaunch", "--", "/p/proton", "waitforexitandrun", "/g/noita.exe"]
    procs = {
        10: steam_cmd,  # Steam's reaper: an ancestor of ours
        11: ["python", "/bin/noita-switcher", "launch", "--", *steam_cmd],  # us
        30: ["/g/Noita/noita_proxy", "--launch-cmd", " ".join(steam_cmd)],  # proxy window
        40: ["python", "/bin/noita-switcher", "launch", "--", *steam_cmd],  # other switcher instance
        50: ["/usr/bin/vim", "notes.txt"],
    }
    _fake_proc(tmp_path, procs)
    assert scan_processes(str(tmp_path), skip={10, 11}) is None
    assert scan_processes(str(tmp_path), skip={11}).startswith("pid 10:")  # only skipping makes it pass

    _fake_proc(tmp_path, {20: ["Z:\\data\\Noita\\noita.exe"]})
    found = scan_processes(str(tmp_path), skip={10, 11})
    assert found and found.startswith("pid 20:")


def test_game_check_with_skip_none_excludes_real_ancestors():
    if sys.platform == "win32":
        pytest.skip("procfs only")
    # outer (argv carries noita.exe, like Steam's reaper) -> inner: inner's ancestors must include outer
    inner = "import os; from noita_switcher.profiles import _ancestor_pids as a; print(os.getppid() in a())"
    outer = f"import subprocess,sys; print(subprocess.run([sys.executable,'-c',{inner!r}],capture_output=True,text=True).stdout.strip())"
    r = subprocess.run(
        [sys.executable, "-c", outer, "noita.exe"], capture_output=True, text=True, env={"PYTHONPATH": str(ROOT)}
    )
    assert r.stdout.strip() == "True"
