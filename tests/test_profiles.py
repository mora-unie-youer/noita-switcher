import io
import tarfile

import pytest

from noita_switcher import profiles
from noita_switcher.profiles import ProfileError, Store


@pytest.fixture(autouse=True)
def game_closed(monkeypatch):
    monkeypatch.setattr(profiles, "running_game_process", lambda: None)


@pytest.fixture
def save(tmp_path):
    d = tmp_path / "save00"
    (d / "persistent/flags").mkdir(parents=True)
    (d / "world").mkdir()
    (d / "persistent/flags/progress").write_text("solo-progress")
    (d / "world/world_state.xml").write_text("solo-run")
    (d / "mod_config.xml").write_text("solo-mods")
    (d / "steam_autocloud.vdf").write_text("marker")
    (d / "world/steam_autocloud.vdf").write_text("marker")
    return d


def snapshot(d):
    return {
        p.relative_to(d).as_posix(): p.read_text()
        for p in d.rglob("*")
        if p.is_file() and not p.name.startswith("noita-switcher.")
    }


def user_files(d):
    return {k: v for k, v in snapshot(d).items() if "steam_autocloud" not in k}


def test_roundtrip_restores_each_profile_and_keeps_steam_markers(save):
    s = Store(save)
    s.new("coop", switch=True)
    assert s.active() == "coop"
    assert user_files(save) == {}  # fresh game
    assert (save / "steam_autocloud.vdf").read_text() == "marker"
    assert (save / "world/steam_autocloud.vdf").read_text() == "marker"

    (save / "persistent/flags").mkdir(parents=True, exist_ok=True)
    (save / "persistent/flags/progress").write_text("coop-progress")

    s.switch("default")
    assert user_files(save) == {
        "persistent/flags/progress": "solo-progress",
        "world/world_state.xml": "solo-run",
        "mod_config.xml": "solo-mods",
    }
    s.switch("coop")
    assert user_files(save) == {"persistent/flags/progress": "coop-progress"}


def test_only_inactive_profiles_have_archives(save):
    s = Store(save)
    s.new("coop")
    s.new("other", source="default")
    archives = sorted(p.name for p in save.glob("noita-switcher.*.tar.gz"))
    assert len(archives) == 2
    s.switch("coop")
    assert len(list(save.glob("noita-switcher.*.tar.gz"))) == 2  # default parked, coop consumed, other kept
    assert [i.name for i in s.list() if i.active] == ["coop"]


def test_interrupted_switch_is_resumable_without_data_loss(save, monkeypatch):
    s = Store(save)
    s.new("coop")
    monkeypatch.setattr(Store, "_extract", lambda self, a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        s.switch("coop")
    monkeypatch.undo()
    monkeypatch.setattr(profiles, "running_game_process", lambda: None)

    assert s.pending() == {"from": "default", "to": "coop"}
    with pytest.raises(ProfileError, match="interrupted"):
        s.new("x")
    s.switch("default")  # roll back to the parked profile
    assert user_files(save)["persistent/flags/progress"] == "solo-progress"
    assert s.pending() is None


def test_archive_with_path_traversal_is_rejected_before_touching_live_files(save):
    s = Store(save)
    s.new("evil")
    archive = next(save.glob("noita-switcher.*.tar.gz"))
    data = b"pwn"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("../escaped.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    with pytest.raises(ProfileError, match="unsafe"):
        s.switch("evil")
    assert not (save.parent / "escaped.txt").exists()
    assert user_files(save)["mod_config.xml"] == "solo-mods"


def test_names_are_case_insensitive_unique_and_active_cannot_be_deleted(save):
    s = Store(save)
    s.new("Coop")
    with pytest.raises(ProfileError, match="exists"):
        s.new("coop")
    with pytest.raises(ProfileError, match="active"):
        s.delete("default")
    s.switch("COOP")
    assert s.active() == "Coop"
    s.delete("default")
    assert [i.name for i in s.list()] == ["Coop"]


def test_refuses_while_game_running(save, monkeypatch):
    s = Store(save)
    s.new("coop")
    monkeypatch.setattr(profiles, "running_game_process", lambda: "pid 42: wine noita.exe")
    with pytest.raises(ProfileError, match="running"):
        s.switch("coop")
    assert user_files(save)["mod_config.xml"] == "solo-mods"
    s.switch("coop", force=True)


def test_other_save_slots_are_part_of_the_profile_but_save_shared_is_not(save):
    root = save.parent
    (root / "save03/world").mkdir(parents=True)
    (root / "save03/world/world_state.xml").write_text("slot3-solo")
    (root / "save03/steam_autocloud.vdf").write_text("marker")
    (root / "save_shared").mkdir()
    (root / "save_shared/config.xml").write_text("video-settings")

    s = Store(save)
    s.new("coop", switch=True)
    assert not (root / "save03/world/world_state.xml").exists()
    assert (root / "save03/steam_autocloud.vdf").read_text() == "marker"
    (root / "save03/world").mkdir(parents=True, exist_ok=True)
    (root / "save03/world/world_state.xml").write_text("slot3-coop")
    (root / "save05").mkdir()  # slot the game creates later
    (root / "save05/player.xml").write_text("slot5-coop")

    s.switch("default")
    assert (root / "save03/world/world_state.xml").read_text() == "slot3-solo"
    assert not (root / "save05/player.xml").exists()
    s.switch("coop")
    assert (root / "save03/world/world_state.xml").read_text() == "slot3-coop"
    assert (root / "save05/player.xml").read_text() == "slot5-coop"
    assert (root / "save_shared/config.xml").read_text() == "video-settings"


def test_archive_in_the_old_save00_relative_format_is_refused_not_misplaced(save):
    s = Store(save)
    s.new("old")
    archive = next(save.glob("noita-switcher.*.tar.gz"))
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("mod_config.xml")
        info.size = 3
        tar.addfile(info, io.BytesIO(b"old"))
    with pytest.raises(ProfileError, match="outside the save slots"):
        s.switch("old")
    assert user_files(save)["mod_config.xml"] == "solo-mods"


def test_new_with_switch_creates_nothing_if_the_game_is_running(save, monkeypatch):
    s = Store(save)
    monkeypatch.setattr(profiles, "running_game_process", lambda: "pid 42: wine noita.exe")
    with pytest.raises(ProfileError, match="running"):
        s.new("first", switch=True)
    assert [i.name for i in s.list()] == ["default"]
