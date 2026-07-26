"""Locate or install a private Python 3.12 + palooz runtime for PlM (Oodle)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

# Official embeddable CPython (Windows x64) — no installer, no admin
PYTHON_VERSION = "3.12.8"
PYTHON_EMBED_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
    f"python-{PYTHON_VERSION}-embed-amd64.zip"
)

APP_NAME = "PalworldMSTool"
_TOOL_ROOT = Path(__file__).resolve().parent.parent

ProgressCb = Callable[[str], None]


def appdata_runtime_dir() -> Path:
    """Standard per-user install location (not Downloads)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME / "runtime" / "python312"


def tool_vendor_dir() -> Path:
    return _TOOL_ROOT / "vendor"


def _palooz_sources() -> list[Path]:
    v = tool_vendor_dir()
    return [
        v / "palooz.pyd",
        v / "palooz.cp312-win_amd64.pyd",
        _TOOL_ROOT / "palooz.pyd",
    ]


def find_palooz_pyd() -> Path | None:
    for p in _palooz_sources():
        if p.is_file():
            return p
    return None


def _is_valid_py312(exe: Path) -> bool:
    if not exe.is_file():
        return False
    try:
        out = subprocess.check_output(
            [str(exe), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
            text=True,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=15,
        ).strip()
        return out.startswith("3.12")
    except Exception:
        return False


def _has_palooz(exe: Path) -> bool:
    try:
        # Ensure vendor is on path for this check
        vendor = str(tool_vendor_dir())
        code = (
            "import sys; "
            f"sys.path.insert(0, r'{vendor}'); "
            "import palooz; print('ok')"
        )
        # Also check next to the exe (runtime install puts palooz there)
        env_code = (
            "import sys; "
            f"sys.path.insert(0, r'{exe.parent}'); "
            f"sys.path.insert(0, r'{vendor}'); "
            "import palooz; print('ok')"
        )
        out = subprocess.check_output(
            [str(exe), "-c", env_code],
            text=True,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=15,
        ).strip()
        return out == "ok"
    except Exception:
        return False


def find_py312() -> Path | None:
    """Return a Python 3.12 executable suitable for PlM work (prefer with palooz)."""
    candidates: list[Path] = []

    # 1) Official app runtime (preferred for end users)
    candidates.append(appdata_runtime_dir() / "python.exe")

    # 2) Next to the tool (portable)
    candidates.append(_TOOL_ROOT / "runtime" / "python312" / "python.exe")
    candidates.append(_TOOL_ROOT / "python312" / "python.exe")

    # 3) Common official installs
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    pf86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    for base in (local / "Programs" / "Python", pf, pf86, Path(r"C:\Python312")):
        candidates.append(base / "Python312" / "python.exe")
        candidates.append(base / "python.exe")

    # 4) py launcher
    try:
        out = subprocess.check_output(
            ["py", "-3.12", "-c", "import sys; print(sys.executable)"],
            text=True,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=15,
        ).strip()
        if out:
            candidates.insert(0, Path(out))
    except Exception:
        pass

    # 5) Legacy dev path (still support if someone has it)
    candidates.append(Path.home() / "Downloads" / "python312" / "python.exe")

    seen: set[str] = set()
    valid: list[Path] = []
    for c in candidates:
        key = str(c).lower()
        if key in seen:
            continue
        seen.add(key)
        if _is_valid_py312(c):
            valid.append(c)

    # Prefer one that already has palooz
    for c in valid:
        if _has_palooz(c):
            return c
    return valid[0] if valid else None


def runtime_status() -> dict:
    """Diagnostic for the UI."""
    py = find_py312()
    palooz = find_palooz_pyd()
    ready = False
    detail = ""
    if py and _has_palooz(py):
        ready = True
        detail = f"Ready · {py}"
    elif py and not _has_palooz(py):
        detail = f"Python 3.12 found but palooz missing · {py}"
    elif not palooz:
        detail = "vendor/palooz.pyd missing from tool folder"
    else:
        detail = f"Python 3.12 not installed (will use {appdata_runtime_dir()})"
    return {
        "ready": ready,
        "python": str(py) if py else None,
        "palooz": str(palooz) if palooz else None,
        "target": str(appdata_runtime_dir()),
        "detail": detail,
    }


def _enable_embed_site(py_dir: Path) -> None:
    """Uncomment 'import site' in python3xx._pth so local modules work."""
    pths = list(py_dir.glob("python*._pth"))
    for pth in pths:
        text = pth.read_text(encoding="utf-8", errors="replace")
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") and "import site" in stripped:
                lines.append("import site")
            else:
                lines.append(line)
        # Ensure vendor-less: palooz sits next to python.exe
        if "import site" not in "\n".join(lines):
            lines.append("import site")
        pth.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _copy_palooz(py_dir: Path, log: ProgressCb) -> None:
    src = find_palooz_pyd()
    if src is None:
        raise FileNotFoundError(
            "vendor/palooz.pyd not found next to the tool. "
            "Re-download the full release zip."
        )
    dest = py_dir / "palooz.pyd"
    shutil.copy2(src, dest)
    log(f"Installed palooz → {dest}")


def install_py312_runtime(log: ProgressCb | None = None) -> Path:
    """
    Download official embeddable Python 3.12 into
    %LOCALAPPDATA%\\PalworldMSTool\\runtime\\python312
    and copy palooz.pyd beside it.
    """
    log = log or (lambda _m: None)
    dest = appdata_runtime_dir()
    dest.mkdir(parents=True, exist_ok=True)
    exe = dest / "python.exe"

    if exe.is_file() and _is_valid_py312(exe):
        log(f"Python 3.12 already at {dest}")
        _enable_embed_site(dest)
        _copy_palooz(dest, log)
        if _has_palooz(exe):
            log("PlM runtime ready.")
            return exe
        raise RuntimeError("palooz failed to load after copy")

    log(f"Downloading official Python {PYTHON_VERSION} embeddable…")
    log(PYTHON_EMBED_URL)

    with tempfile.TemporaryDirectory() as td:
        zpath = Path(td) / "python-embed.zip"
        try:
            urllib.request.urlretrieve(PYTHON_EMBED_URL, zpath)  # noqa: S310
        except Exception as e:
            raise RuntimeError(
                f"Download failed. Check internet connection.\n{e}"
            ) from e

        log("Extracting…")
        # Clean partial install
        if dest.exists():
            for child in dest.iterdir():
                if child.is_file():
                    child.unlink()
                else:
                    shutil.rmtree(child, ignore_errors=True)

        with zipfile.ZipFile(zpath, "r") as zf:
            zf.extractall(dest)

    if not exe.is_file():
        raise RuntimeError(f"python.exe missing after extract: {dest}")

    _enable_embed_site(dest)
    _copy_palooz(dest, log)

    if not _is_valid_py312(exe):
        raise RuntimeError("Installed Python failed version check")
    if not _has_palooz(exe):
        raise RuntimeError(
            "Installed Python but palooz could not be imported. "
            "Make sure vendor/palooz.pyd is present."
        )

    log(f"Done. Runtime: {exe}")
    return exe


def ensure_py312(log: ProgressCb | None = None) -> Path:
    """Return working py3.12+palooz, installing into AppData if needed."""
    log = log or (lambda _m: None)
    existing = find_py312()
    if existing and _has_palooz(existing):
        return existing
    if existing and not _has_palooz(existing):
        # Try drop palooz next to it only if it's our appdata runtime
        try:
            if appdata_runtime_dir() in existing.parents or existing.parent == appdata_runtime_dir():
                _copy_palooz(existing.parent, log)
                if _has_palooz(existing):
                    return existing
        except Exception:
            pass
    return install_py312_runtime(log)
