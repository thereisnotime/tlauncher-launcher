"""ui.base.GUIBase is type-checking scaffolding and must stay invisible at runtime."""

import ast
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

from gui import MinecraftLauncherGUI  # noqa: E402
from ui.base import GUIBase  # noqa: E402

BASE_SRC = Path(__file__).parent.parent / "ui" / "base.py"


def test_base_is_last_in_mro():
    assert MinecraftLauncherGUI.__mro__[-2:] == (GUIBase, object)


def test_base_defines_nothing_at_runtime():
    assert [k for k in vars(GUIBase) if not k.startswith("__")] == []


def test_every_stub_has_a_real_implementation():
    stubs = [
        n.name for n in ast.walk(ast.parse(BASE_SRC.read_text())) if isinstance(n, ast.FunctionDef)
    ]
    mixins = MinecraftLauncherGUI.__mro__[:-2]
    missing = [s for s in stubs if not any(s in vars(k) for k in mixins)]
    assert stubs
    assert missing == []
