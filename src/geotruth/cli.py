"""The ``geotruth`` command-line dispatcher.

Every subcommand lives in its own module, so adding one never means editing a shared
file. A command is found in two places:

1. **Built-in:** any module ``geotruth/commands/<name>.py`` (names starting with ``_``
   are skipped). ``foo_bar.py`` becomes ``geotruth foo-bar`` unless it sets ``NAME``.
2. **Plugins:** entry points in the group ``geotruth.commands`` whose value is a module
   (``mycmd = "mypackage.mycmd"``) following the same protocol.

A command module provides::

    NAME = "relate"                      # optional; defaults to the module name
    HELP = "print the exact DE-9IM matrix"  # optional; defaults to the docstring's 1st line

    def add_arguments(parser: argparse.ArgumentParser) -> None:   # optional
        parser.add_argument("a")

    def run(args: argparse.Namespace) -> int | None:              # required
        ...                                                        # exit status (None = 0)

Keep module-level imports light: every command module is imported to build ``--help``.
A module that fails to import does not break the others; its command reports the error.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import metadata
from types import ModuleType

from geotruth import ENGINE_VERSION, __version__

__all__ = ["COMMAND_PACKAGE", "ENTRY_POINT_GROUP", "Command", "build_parser", "discover", "main"]

#: Package scanned for built-in commands.
COMMAND_PACKAGE = "geotruth.commands"
#: Entry-point group for commands provided by other distributions.
ENTRY_POINT_GROUP = "geotruth.commands"


@dataclass
class Command:
    """A registered subcommand."""

    name: str
    help: str
    module: str
    run: Callable[[argparse.Namespace], int | None]
    add_arguments: Callable[[argparse.ArgumentParser], None] | None = None
    error: str | None = None  # why the module could not be loaded, if it could not


def _from_module(mod: ModuleType, default_name: str) -> Command:
    name = getattr(mod, "NAME", None) or default_name.replace("_", "-")
    doc = (mod.__doc__ or "").strip().splitlines()
    help_text = getattr(mod, "HELP", None) or (doc[0] if doc else "")
    run = getattr(mod, "run", None)
    if not callable(run):
        raise TypeError(f"command module {mod.__name__} has no run(args) function")
    return Command(
        name=name,
        help=help_text,
        module=mod.__name__,
        run=run,
        add_arguments=getattr(mod, "add_arguments", None),
    )


def _broken(name: str, module: str, exc: BaseException) -> Command:
    detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()

    def run(args: argparse.Namespace) -> int:
        print(f"geotruth {name}: this command failed to load ({module}): {detail}", file=sys.stderr)
        return 2

    return Command(name=name, help=f"(unavailable: {detail})", module=module, run=run, error=detail)


def _builtin_modules() -> list[str]:
    pkg = importlib.import_module(COMMAND_PACKAGE)
    return sorted(m.name for m in pkgutil.iter_modules(pkg.__path__) if not m.name.startswith("_"))


def _entry_points() -> list[metadata.EntryPoint]:
    try:
        return list(metadata.entry_points(group=ENTRY_POINT_GROUP))
    except Exception:  # a broken environment must not break the CLI
        return []


def discover() -> dict[str, Command]:
    """All available commands by name: built-ins first, then entry-point plugins
    (a plugin cannot shadow a built-in)."""
    commands: dict[str, Command] = {}
    for modname in _builtin_modules():
        full = f"{COMMAND_PACKAGE}.{modname}"
        try:
            cmd = _from_module(importlib.import_module(full), modname)
        except Exception as exc:  # one broken command must not break the others
            cmd = _broken(modname.replace("_", "-"), full, exc)
        commands.setdefault(cmd.name, cmd)
    for ep in _entry_points():
        if ep.name in commands:
            continue
        try:
            cmd = _from_module(ep.load(), ep.name)
        except Exception as exc:  # one broken command must not break the others
            cmd = _broken(ep.name, ep.value, exc)
        commands.setdefault(cmd.name, cmd)
    return dict(sorted(commands.items()))


def build_parser(commands: dict[str, Command]) -> argparse.ArgumentParser:
    """The top-level parser with one subparser per command."""
    parser = argparse.ArgumentParser(
        prog="geotruth",
        description="Exact ground truth for computational geometry.",
    )
    parser.add_argument(
        "--version", action="version", version=f"geotruth {__version__} (engine {ENGINE_VERSION})"
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    for cmd in commands.values():
        p = sub.add_parser(cmd.name, help=cmd.help, description=cmd.help)
        if cmd.add_arguments is not None and cmd.error is None:
            cmd.add_arguments(p)
        p.set_defaults(_command=cmd)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of the ``geotruth`` console script; returns the exit status."""
    commands = discover()
    parser = build_parser(commands)
    args = parser.parse_args(argv)
    cmd: Command | None = getattr(args, "_command", None)
    if cmd is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        status = cmd.run(args)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:  # e.g. `geotruth ... | head`
        return 0
    return 0 if status is None else int(status)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
