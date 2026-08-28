"""Architectural invariants.

These tests exist because the rules they check are easy to break by accident and
expensive to discover late. They are cheap, and they fail loudly.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "bob"

#: Packages that make up the headless kernel. None of them may touch Qt.
KERNEL_PACKAGES = ("core", "config", "providers", "tools", "utils")

#: The single sanctioned door between the two worlds.
BRIDGE = SRC / "ui" / "bridge.py"


def imported_modules(path: Path) -> set[str]:
    """Top-level module names imported by a Python file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def python_files(*packages: str) -> list[Path]:
    return [path for package in packages for path in (SRC / package).rglob("*.py")]


@pytest.mark.parametrize("package", KERNEL_PACKAGES)
def test_kernel_never_imports_qt(package: str) -> None:
    """The core must stay runnable, and testable, with no Qt installed."""
    offenders = [
        path.relative_to(SRC)
        for path in python_files(package)
        if "PySide6" in imported_modules(path)
    ]
    assert not offenders, f"Qt imported inside the kernel: {offenders}"


def test_kernel_never_imports_the_ui_package() -> None:
    """Dependencies point one way: the UI knows the kernel, never the reverse."""
    offenders = []
    for path in python_files(*KERNEL_PACKAGES):
        text = path.read_text(encoding="utf-8")
        if "from bob.ui" in text or "import bob.ui" in text:
            offenders.append(path.relative_to(SRC))
    assert not offenders, f"kernel imports the UI: {offenders}"


def test_pure_ui_logic_modules_stay_qt_free() -> None:
    """The presenter, view model and design tokens must be testable headlessly."""
    pure = [
        SRC / "ui" / "presenter.py",
        SRC / "ui" / "viewmodel.py",
        SRC / "ui" / "visual.py",
        SRC / "ui" / "responsive.py",
        SRC / "ui" / "intents.py",
        SRC / "ui" / "captions.py",
        SRC / "ui" / "runtime.py",
        SRC / "ui" / "theme" / "tokens.py",
        SRC / "ui" / "theme" / "color.py",
        SRC / "ui" / "theme" / "stylesheet.py",
    ]
    offenders = [p.name for p in pure if "PySide6" in imported_modules(p)]
    assert not offenders, f"these must not import Qt: {offenders}"


def test_dev_tooling_stays_out_of_the_kernel() -> None:
    """Demo scenarios must never become something production code depends on."""
    offenders = [
        path.relative_to(SRC)
        for path in python_files(*KERNEL_PACKAGES)
        if "bob.dev" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"kernel depends on dev tooling: {offenders}"


def test_headless_run_imports_no_qt() -> None:
    """The strongest form of the rule: prove it at runtime, not just statically.

    Runs a real headless boot in a subprocess and asserts PySide6 never landed in
    ``sys.modules``.
    """
    code = (
        "import sys, asyncio\n"
        "from bob.config.loader import load_settings\n"
        "from bob.providers import load_all\n"
        "from bob.app import run_headless\n"
        "load_all()\n"
        "asyncio.run(run_headless(load_settings()))\n"
        "loaded = [m for m in sys.modules if m.startswith('PySide6')]\n"
        "sys.exit(1 if loaded else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, "headless boot pulled in Qt:\n" + result.stdout + result.stderr


def test_only_the_bridge_imports_both_worlds() -> None:
    """Exactly one file is allowed to see Qt and the kernel at the same time."""
    both: list[str] = []
    for path in (SRC / "ui").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        touches_qt = "PySide6" in text
        touches_kernel = "bob.core.kernel" in text or "KernelRuntime" in text
        if touches_qt and touches_kernel and path != BRIDGE:
            both.append(path.relative_to(SRC).as_posix())
    # ui/app.py is the composition root and is expected to see both.
    assert both == ["ui/app.py"], f"unexpected Qt/kernel crossovers: {both}"
