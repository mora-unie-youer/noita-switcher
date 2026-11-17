# noita-switcher

Named profiles for Noita's saves (`save00`..`save06`). Stdlib-only Python ≥ 3.10.

```
uv tool install .            # or: pipx install .

noita-switcher                       # list profiles (* = active)
noita-switcher new coop -s           # create empty profile "coop" and switch to it
noita-switcher new hard --from solo  # create as a copy of "solo"
noita-switcher use solo              # switch
noita-switcher rename solo main
noita-switcher delete coop           # -y to skip the prompt; active profile can't be deleted
noita-switcher where                 # detected save00 path
```

The first run adopts the existing save as profile `default`.

## Launching from Steam (solo / coop)

Mark profiles, then make Steam's Play button ask which one to start:

```
noita-switcher mode duo coop        # or: new duo --mode coop   (default mode is solo)
noita-switcher launch-option        # prints the line to paste into Steam
```

Steam > Noita > Properties > Launch Options (keep your own env/wrapper prefixes in front):

```
/home/you/.local/bin/noita-switcher launch -- %command%
```

Play → dialog (zenity or kdialog; terminal prompt if run from one) with all profiles and their mode →
the save is switched → **solo**: Noita starts as usual; **coop**: `noita_proxy` starts with
`--launch-cmd "<Steam's command>"`, so its "Start game" button launches Noita exactly like Steam would.
Cancelling the dialog starts nothing. `noita-switcher launch --profile NAME -- %command%` skips the dialog.

`noita_proxy` is found next to `noita.exe` (newest of `noita_proxy` / `noita_proxy.x86_64`). Override with
`noita-switcher proxy PATH` (stored per machine in `~/.config/noita-switcher/config.json`, `proxy --auto` clears it)
or `$NOITA_PROXY`. Profile modes are stored in `save00` and sync through Steam Cloud with the profiles.

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

`mod_config.xml` / `mod_settings.bin` are part of a profile, so mod sets can differ per profile.
`save_shared` (video/audio/key settings) is global and not touched.

## Safety

* Refuses to switch while `noita.exe` runs (`--force` to override).
* The target archive is validated, and the current profile is archived, before any live file is deleted.
* An interrupted switch is recorded; re-running `use <profile>` finishes or rolls it back.
* Extracted files get a fresh mtime so Steam's conflict resolution doesn't prefer a stale remote copy.
* `steam_autocloud.vdf` markers are never touched.

Switch on one machine at a time and let Steam finish syncing (exit Noita, wait for the cloud
upload) before switching on another.
