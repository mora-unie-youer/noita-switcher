# noita-switcher

Named profiles for Noita's saves (`save00`..`save06`): keep separate progress for solo, co-op or any
other run, and switch between them with one command. Profiles sync through Steam Cloud.

* Unlimited profiles, each with a name and a mode (`solo` / `coop`)
* Create, copy, switch, rename, delete: one command each
* Optional Steam integration: the Play button asks which profile to start

## Installation

**Requirements:** Python ≥ 3.10 and [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/).
No third-party Python dependencies.

```
git clone https://github.com/mora-unie-youer/noita-switcher.git
cd noita-switcher
uv tool install .            # or: pipx install .
```

Check that it works:

```
noita-switcher where         # detected save00 path, marked with *
noita-switcher               # profile list
```

If `where` finds nothing, or finds the wrong directory, pass it explicitly with `--dir PATH` or set
`$NOITA_SAVE_DIR` (see [Save directory detection](#save-directory-detection)).

To update, run `git pull` in the clone, then reinstall (`uv tool install --reinstall .`,
`pipx install --force .`). To remove: `uv tool uninstall noita-switcher` / `pipx uninstall noita-switcher`.

## Quick start

1. **Close Noita.** Profiles can't be switched while the game runs.
2. Run `noita-switcher`. On the first run your current save is adopted as the profile `default`;
   nothing is lost or moved.
3. Create a profile and switch to it:
   ```
   noita-switcher new coop --mode coop -s
   ```
4. Start Noita and play. Progress goes into the active profile.
5. Exit Noita, wait for Steam to finish the cloud upload, then switch back whenever you want:
   ```
   noita-switcher use default
   ```

## Usage

### Everyday commands

| Command | What it does |
|---|---|
| `noita-switcher` (or `list`, `ls`) | List profiles. `*` marks the active one; shows mode, size and creation date |
| `noita-switcher current` | Print the active profile name only |
| `noita-switcher new NAME` | Create an empty profile (a fresh start for the game) |
| `noita-switcher new NAME -s` | Create it and switch to it right away |
| `noita-switcher new NAME --from OTHER` | Create it as a copy of `OTHER` (e.g. to try a risky build without losing progress) |
| `noita-switcher new NAME --mode coop` | Create it marked as co-op (default: `solo`) |
| `noita-switcher use NAME` (or `switch`) | Make `NAME` the active profile |
| `noita-switcher mode NAME solo\|coop` | Change a profile's mode |
| `noita-switcher rename OLD NEW` | Rename a profile |
| `noita-switcher delete NAME` (or `rm`) | Delete a profile permanently; asks for confirmation, `-y` skips it. The active profile can't be deleted |
| `noita-switcher where` | Show the detected `save00` path(s) |

Global option: `--dir PATH` uses a specific `save00` directory.

### Example session

```
$ noita-switcher
* default  solo     84.2 MiB  created 2026-11-17

$ noita-switcher new coop --mode coop
created 'coop' (coop, empty)

$ noita-switcher new hard --from default
created 'hard' (solo, copy of 'default')

$ noita-switcher use coop
active profile: coop

$ noita-switcher
  default  solo     84.2 MiB  created 2026-11-17
* coop     coop      1.1 MiB  created 2026-11-18
  hard     solo     84.2 MiB  created 2026-11-18
```

(Illustrative output. Size is the uncompressed size of the profile's files.)

### Things to know

* **Switching replaces the live `save00`.** The current profile is archived first, so its progress is kept
  under its own name.
* **`new NAME` without `--from` is empty:** Noita starts from scratch the next time you launch it.
* **`save_shared`** (video/audio/key settings) is global and shared by all profiles.
* **Mods:** `mod_config.xml` / `mod_settings.bin` belong to the profile, so each profile can have its own mod set.
* **Noita running?** The command refuses to run. `--force` overrides this; use it only if you know the game is closed.

## Launching from Steam (solo / co-op)

Instead of switching in a terminal before every session, let Steam's Play button ask which profile to start.

1. Mark your profiles with a mode (once):
   ```
   noita-switcher mode default solo
   noita-switcher mode coop coop        # or create it with: new coop --mode coop
   ```
2. Print the launch option for your machine:
   ```
   noita-switcher launch-option
   ```
3. In Steam: **Noita → Properties → Launch Options**, paste the printed line. It looks like:
   ```
   /home/you/.local/bin/noita-switcher launch -- %command%
   ```
   If you already use env vars or wrappers there (`gamemoderun`, `taskset`, ...), keep them in front of it.
4. Press **Play**. A dialog (zenity or kdialog; a terminal prompt if started from a terminal) lists all
   profiles with their modes. After you pick one:
   * the save is switched to it;
   * **solo**: Noita starts as usual;
   * **coop**: `noita_proxy` starts with `--launch-cmd "<Steam's command>"`, so its *Start game* button
     launches Noita exactly like Steam would.
5. Cancelling the dialog starts nothing.

To skip the dialog and always use one profile: `noita-switcher launch --profile NAME -- %command%`.

If something goes wrong, an error dialog is shown and the details are written to
`~/.local/state/noita-switcher/launch.log` (`$XDG_STATE_HOME` is respected; on Windows it sits next to the config file).

### noita_proxy

`noita_proxy` is looked up next to `noita.exe` (newest of `noita_proxy` / `noita_proxy.x86_64`). To override:

```
noita-switcher proxy              # show the one in use
noita-switcher proxy /path/to/noita_proxy
noita-switcher proxy --auto       # forget the override, auto-detect again
```

The path is stored per machine in `~/.config/noita-switcher/config.json`. `$NOITA_PROXY` also works.
Profile modes are stored in `save00` and sync through Steam Cloud together with the profiles.

## Save directory detection

Checks every Steam library from `libraryfolders.vdf` for
`steamapps/compatdata/881100/pfx/.../Nolla_Games_Noita/save00` (so a save on another
mounted drive is found), plus Flatpak/Snap Steam roots and native Windows
`%LOCALAPPDATA%Low`. Override with `--dir` or `$NOITA_SAVE_DIR`.

## How it syncs with Steam Cloud

Noita's Auto-Cloud rules cover `save00` itself (files directly in it) and a fixed set of its
sub-folders (`world`, `persistent`, `stats`, ...). Arbitrary extra folders are not synced, so:

* active profile = the live `save00` and any `save01`..`save06` the game created (synced by Steam as usual);
* every other profile = one `noita-switcher.<id>.tar.gz` file in the `save00` root;
* `noita-switcher.json` holds names and the active profile.

**Multiple machines:** switch on one machine at a time and let Steam finish syncing (exit Noita, wait
for the cloud upload) before switching on another.

## Safety

* Refuses to switch while `noita.exe` runs (`--force` to override).
* The target archive is validated, and the current profile is archived, before any live file is deleted.
* An interrupted switch is recorded; re-running `use <profile>` finishes or rolls it back
  (`list` shows a warning when one is pending).
* Extracted files get a fresh mtime so Steam's conflict resolution doesn't prefer a stale remote copy.
* `steam_autocloud.vdf` markers are never touched.
