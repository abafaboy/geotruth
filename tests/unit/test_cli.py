"""Tests of the geotruth CLI dispatcher and the version command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types

import pytest

from geotruth import ENGINE_VERSION, __version__, cli


def test_version_command(capsys):
    assert cli.main(["version"]) == 0
    out = capsys.readouterr().out
    assert f"geotruth {__version__} (engine {ENGINE_VERSION})" in out


def test_version_json(capsys):
    assert cli.main(["version", "--json"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["geotruth"] == __version__ and info["engine"] == ENGINE_VERSION
    assert info["rational_backend"] in ("gmpy2", "fractions")
    assert set(info) == {"geotruth", "engine", "python", "gmpy2", "rational_backend"}


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["--version"])
    assert info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_prints_help(capsys):
    assert cli.main([]) == 2
    assert "COMMAND" in capsys.readouterr().err


def test_unknown_command_is_an_error(capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["no-such-command"])
    assert info.value.code == 2


def test_discover_finds_builtin_commands():
    commands = cli.discover()
    assert "version" in commands
    cmd = commands["version"]
    assert cmd.module == "geotruth.commands.version" and cmd.error is None
    assert cmd.help.startswith("print geotruth")


def _module(name: str, doc: str | None = None, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name, doc)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def test_command_protocol_defaults():
    mod = _module("pkg.foo_bar", "Do the foo bar.\n\nMore text.", run=lambda args: 3)
    cmd = cli._from_module(mod, "foo_bar")
    assert cmd.name == "foo-bar" and cmd.help == "Do the foo bar." and cmd.add_arguments is None
    mod2 = _module("pkg.x", None, NAME="renamed", HELP="h", run=lambda a: None)
    assert cli._from_module(mod2, "x").name == "renamed"
    with pytest.raises(TypeError):
        cli._from_module(_module("pkg.norun"), "norun")


class FakeEntryPoint:
    def __init__(self, name, value, target=None, exc=None):
        self.name, self.value, self._target, self._exc = name, value, target, exc

    def load(self):
        if self._exc:
            raise self._exc
        return self._target


def test_entry_point_plugins(monkeypatch, capsys):
    calls = []

    def add_arguments(p):
        p.add_argument("--n", type=int, default=1)

    plugin = _module(
        "ext.hello", "Say hello.", run=lambda a: calls.append(a.n) or 0, add_arguments=add_arguments
    )
    shadow = _module("ext.version", "Shadow.", run=lambda a: 99)
    monkeypatch.setattr(
        cli,
        "_entry_points",
        lambda: [
            FakeEntryPoint("hello", "ext.hello", plugin),
            FakeEntryPoint("version", "ext.version", shadow),  # cannot shadow a built-in
            FakeEntryPoint("broken", "ext.broken", exc=ImportError("no module named ext.broken")),
        ],
    )
    commands = cli.discover()
    assert commands["version"].module == "geotruth.commands.version"
    assert cli.main(["hello", "--n", "5"]) == 0 and calls == [5]
    assert commands["broken"].error and "no module named" in commands["broken"].help
    assert cli.main(["broken"]) == 2
    assert "failed to load" in capsys.readouterr().err


def test_broken_builtin_does_not_break_the_cli(monkeypatch):
    real_import = cli.importlib.import_module

    def fake_import(name, *a, **kw):
        if name == "geotruth.commands.version":
            raise SyntaxError("oops")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(cli.importlib, "import_module", fake_import)
    commands = cli.discover()
    assert commands["version"].error is not None
    assert cli.main(["version"]) == 2


def test_python_dash_m(repo_root):
    env = {**os.environ, "PYTHONPATH": str(repo_root / "src")}
    out = subprocess.run(
        [sys.executable, "-m", "geotruth", "version"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=60,
    )
    assert out.stdout.startswith(f"geotruth {__version__}")
