from __future__ import annotations

import argparse
import shlex
import shutil
import sys
import time

from . import config
from .launch import find_proxy, launch, show_error
from .locate import find_candidates, find_save_dir
from .profiles import MODES, ProfileError, Store


def _fmt_size(n: int | None) -> str:
    if n is None:
        return "MISSING"
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError


def _cmd_list(store: Store, _args) -> None:
    infos = store.list()
    width = max(len(i.name) for i in infos)
    for i in infos:
        created = time.strftime("%Y-%m-%d", time.localtime(i.created))
        print(f"{'*' if i.active else ' '} {i.name:<{width}}  {i.mode:<4}  {_fmt_size(i.size):>10}  created {created}")
    pending = store.pending()
    if pending:
        print(f"\n! switch {pending['from']!r} -> {pending['to']!r} was interrupted; run `use <profile>` to finish")


def _cmd_current(store: Store, _args) -> None:
    print(store.active())


def _cmd_new(store: Store, args) -> None:
    store.new(args.name, source=args.source, switch=args.switch, force=args.force, mode=args.mode)
    what = f"copy of {args.source!r}" if args.source else "empty"
    print(f"created {args.name!r} ({args.mode}, {what})" + ("; now active" if args.switch else ""))


def _cmd_use(store: Store, args) -> None:
    if store.switch(args.name, force=args.force):
        print(f"active profile: {store.active()}")
    else:
        print(f"{store.active()!r} is already active")


def _cmd_mode(store: Store, args) -> None:
    store.set_mode(args.name, args.mode)
    print(f"{args.name!r} is now {args.mode}")


def _cmd_rename(store: Store, args) -> None:
    store.rename(args.old, args.new)
    print(f"renamed {args.old!r} -> {args.new!r}")


def _cmd_delete(store: Store, args) -> None:
    if not args.yes:
        if not sys.stdin.isatty():
            raise ProfileError("refusing to delete without confirmation; pass -y")
        if input(f"Delete profile {args.name!r} permanently? [y/N] ").strip().lower() not in ("y", "yes"):
            print("aborted")
            return
    store.delete(args.name)
    print(f"deleted {args.name!r}")


def _cmd_launch(store: Store, args) -> int:
    return launch(store, args.command, args.profile, force=args.force, proxy=args.proxy)


def _cmd_proxy(args) -> None:
    if args.path or args.auto:
        cfg = config.load()
        if args.auto:
            cfg.pop("proxy", None)
        else:
            cfg["proxy"] = str(args.path)
        config.save(cfg)
    found = find_proxy()
    print(f"{found[0]}  ({found[1]})" if found else "noita_proxy not found")


def _cmd_launch_option(_args) -> None:
    exe = shutil.which("noita-switcher")
    prog = shlex.quote(exe) if exe else f"{shlex.quote(sys.executable)} -m noita_switcher"
    print("Steam > Noita > Properties > Launch Options:\n")
    print(f"  {prog} launch -- %command%\n")
    print("Keep any env/wrapper prefixes you already use in front of it, e.g.")
    print(f"  WINE_CPU_TOPOLOGY=8:0,1,2,3,4,5,6,7 gamemoderun taskset -c 0-7 {prog} launch -- %command%")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="noita-switcher", description="Switch Noita save00 between named profiles.")
    p.add_argument("--dir", help="path to save00 (default: auto-detect, or $NOITA_SAVE_DIR)")
    sub = p.add_subparsers(dest="cmd", metavar="command")

    sub.add_parser("list", aliases=["ls"], help="list profiles (default)").set_defaults(fn=_cmd_list)
    sub.add_parser("current", help="print the active profile name").set_defaults(fn=_cmd_current)
    sub.add_parser("where", help="print the detected save00 path")
    sub.add_parser("launch-option", help="print the Steam launch option to use").set_defaults(fn=None)

    s = sub.add_parser("new", help="create a profile")
    s.add_argument("name")
    s.add_argument("--mode", choices=MODES, default="solo", help="how Steam launches it (default: solo)")
    s.add_argument("--from", dest="source", metavar="PROFILE", help="copy an existing profile instead of starting empty")
    s.add_argument("-s", "--switch", action="store_true", help="switch to it right away")
    s.add_argument("--force", action="store_true", help="do not check whether Noita is running")
    s.set_defaults(fn=_cmd_new)

    s = sub.add_parser("use", aliases=["switch"], help="switch to a profile")
    s.add_argument("name")
    s.add_argument("--force", action="store_true", help="do not check whether Noita is running")
    s.set_defaults(fn=_cmd_use)

    s = sub.add_parser("mode", help="mark a profile as solo or coop")
    s.add_argument("name")
    s.add_argument("mode", choices=MODES)
    s.set_defaults(fn=_cmd_mode)

    s = sub.add_parser("rename", help="rename a profile")
    s.add_argument("old")
    s.add_argument("new")
    s.set_defaults(fn=_cmd_rename)

    s = sub.add_parser("delete", aliases=["rm"], help="delete an inactive profile")
    s.add_argument("name")
    s.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    s.set_defaults(fn=_cmd_delete)

    s = sub.add_parser(
        "launch",
        help="Steam launch wrapper: choose a profile, switch, start solo (game) or coop (noita_proxy)",
        description="Use as a Steam launch option: noita-switcher launch -- %command%",
    )
    s.add_argument("--profile", help="skip the dialog and use this profile")
    s.add_argument("--force", action="store_true", help="do not check whether Noita is running")
    s.add_argument("--proxy", metavar="PATH", help="noita_proxy executable (default: configured / auto-detected)")
    s.add_argument("command", nargs=argparse.REMAINDER, help="-- %%command%% from Steam")
    s.set_defaults(fn=_cmd_launch)

    s = sub.add_parser("proxy", help="show or set the noita_proxy executable used for coop profiles")
    s.add_argument("path", nargs="?", help="set this path")
    s.add_argument("--auto", action="store_true", help="forget the configured path and auto-detect")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.cmd == "where":
            chosen = find_save_dir(args.dir)
            for c in find_candidates():
                print(f"{'*' if c == chosen else ' '} {c}")
            if args.dir:
                print(f"* {chosen}  (--dir)")
            return 0
        if args.cmd == "proxy":
            _cmd_proxy(args)
            return 0
        if args.cmd == "launch-option":
            _cmd_launch_option(args)
            return 0
        store = Store(find_save_dir(args.dir))
        rc = (getattr(args, "fn", None) or _cmd_list)(store, args)
        if store.adopted:
            print(f"note: adopted existing save as profile {store.active()!r}", file=sys.stderr)
        return rc or 0
    except (ProfileError, FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        if args.cmd == "launch":
            config.log(f"error: {e}")
            show_error(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
