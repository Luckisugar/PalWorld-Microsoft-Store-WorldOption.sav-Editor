"""Palworld .sav compress/decompress and WorldOption int edits."""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path

# Optional Oodle (PlM) via vendor palooz
_palooz = None
_palooz_error: str | None = None
_TOOL_ROOT = Path(__file__).resolve().parent.parent


def _find_py312() -> Path | None:
    candidates = [
        _TOOL_ROOT.parent / "python312" / "python.exe",
        Path(r"C:\Users\Luckysugar\Downloads\python312\python.exe"),
        _TOOL_ROOT / "python312" / "python.exe",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _load_palooz():
    global _palooz, _palooz_error
    if _palooz is not None:
        return _palooz
    if _palooz_error is not None and _palooz is None:
        # already failed in-process; may still use worker
        pass
    try:
        import palooz  # type: ignore

        _palooz = palooz
        return _palooz
    except Exception:
        pass

    roots = [
        _TOOL_ROOT / "vendor",
        _TOOL_ROOT,
    ]
    for root in roots:
        for name in ("palooz.pyd", "palooz.cp312-win_amd64.pyd"):
            pyd = root / name
            if pyd.is_file():
                sys.path.insert(0, str(root))
                try:
                    import palooz  # type: ignore

                    _palooz = palooz
                    return _palooz
                except Exception as e:
                    _palooz_error = str(e)
    if _palooz_error is None:
        _palooz_error = "palooz not available in this Python"
    return None


def _worker_json(args: list[str]) -> dict:
    py = _find_py312()
    if py is None:
        raise RuntimeError(
            "PlM (Oodle) saves need Python 3.12 + palooz. "
            "Expected Downloads\\python312\\python.exe"
        )
    worker = _TOOL_ROOT / "palworld_ms" / "sav_worker.py"
    cmd = [str(py), str(worker), *args]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_TOOL_ROOT),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            (proc.stderr or proc.stdout or f"worker exit {proc.returncode}").strip()
        )
    line = (proc.stdout or "").strip().splitlines()[-1]
    return json.loads(line)


def parse_header(data: bytes) -> tuple[int, int, bytes, int, int]:
    unc = int.from_bytes(data[0:4], "little")
    cmp = int.from_bytes(data[4:8], "little")
    magic = data[8:11]
    save_type = data[11]
    offset = 12
    if magic == b"CNK":
        unc = int.from_bytes(data[12:16], "little")
        cmp = int.from_bytes(data[16:20], "little")
        magic = data[20:23]
        save_type = data[23]
        offset = 24
    return unc, cmp, magic, save_type, offset


def decompress_sav(data: bytes) -> tuple[bytes, bytes, int]:
    unc, cmp, magic, save_type, offset = parse_header(data)
    payload = data[offset : offset + cmp]
    if magic == b"PlZ":
        out = zlib.decompress(payload)
        if save_type == 0x32:
            out = zlib.decompress(out)
    elif magic == b"PlM":
        palooz = _load_palooz()
        if palooz is None:
            raise RuntimeError(
                _palooz_error
                or "palooz missing — use set_coop via worker for PlM files"
            )
        out = palooz.decompress(payload, unc)
    else:
        raise ValueError(f"Unknown save magic: {magic!r}")
    if len(out) != unc:
        raise ValueError(f"Decompress size mismatch: {len(out)} != {unc}")
    return out, magic, save_type


def compress_sav(gvas: bytes, magic: bytes = b"PlM", save_type: int = 0x31) -> bytes:
    if magic == b"PlZ":
        compressed = zlib.compress(gvas)
        if save_type == 0x32:
            compressed = zlib.compress(compressed)
    elif magic == b"PlM":
        palooz = _load_palooz()
        if palooz is None:
            raise RuntimeError(_palooz_error or "palooz missing")
        # Kraken=8, Normal=4
        compressed = palooz.compress(8, 4, gvas, len(gvas))
        if not compressed:
            raise RuntimeError("palooz compress returned empty")
        save_type = 0x31
    else:
        raise ValueError(f"Unknown magic {magic!r}")
    return (
        len(gvas).to_bytes(4, "little")
        + len(compressed).to_bytes(4, "little")
        + magic
        + bytes([save_type])
        + compressed
    )


def read_worldoption_ints(path: Path) -> dict:
    """Read key ints from a WorldOption.sav (PlZ in-process, PlM via 3.12 worker)."""
    data = path.read_bytes()
    _, _, magic, _, _ = parse_header(data)
    if magic == b"PlM" and _load_palooz() is None:
        return _worker_json(["read_ints", "--in", str(path)])
    gvas, magic_b, _ = decompress_sav(data)
    return {
        "magic": magic_b.decode("ascii", errors="replace"),
        "CoopPlayerMaxNum": get_int_property(gvas, "CoopPlayerMaxNum"),
        "ServerPlayerMaxNum": get_int_property(gvas, "ServerPlayerMaxNum"),
        "GuildPlayerMaxNum": get_int_property(gvas, "GuildPlayerMaxNum"),
    }


def get_int_property(gvas: bytes, name: str) -> int | None:
    key = name.encode("ascii") + b"\x00"
    idx = gvas.find(key)
    if idx < 0:
        return None
    after = idx + len(key)
    type_len = int.from_bytes(gvas[after : after + 4], "little")
    type_name = gvas[after + 4 : after + 4 + type_len]
    if b"IntProperty" not in type_name:
        return None
    size_off = after + 4 + type_len
    size = int.from_bytes(gvas[size_off : size_off + 8], "little")
    val_off = size_off + 8 + 1
    if size != 4 or val_off + 4 > len(gvas):
        return None
    return struct.unpack_from("<i", gvas, val_off)[0]


def set_int_property(gvas: bytearray, name: str, value: int) -> int | None:
    """Set IntProperty; returns previous value or None if missing."""
    key = name.encode("ascii") + b"\x00"
    idx = gvas.find(key)
    if idx < 0:
        return None
    after = idx + len(key)
    type_len = int.from_bytes(gvas[after : after + 4], "little")
    type_name = gvas[after + 4 : after + 4 + type_len]
    if b"IntProperty" not in type_name:
        return None
    size_off = after + 4 + type_len
    size = int.from_bytes(gvas[size_off : size_off + 8], "little")
    val_off = size_off + 8 + 1
    if size != 4 or val_off + 4 > len(gvas):
        return None
    old = struct.unpack_from("<i", gvas, val_off)[0]
    struct.pack_into("<i", gvas, val_off, value)
    return old


def edit_worldoption_coop(
    data: bytes,
    coop_max: int,
    *,
    keep_format: bool = True,
) -> tuple[bytes, dict]:
    """Return new WorldOption.sav bytes + report dict."""
    _, _, magic, _, _ = parse_header(data)
    if magic == b"PlM" and _load_palooz() is None:
        # Must use worker — write temp files
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tin = Path(td) / "in.sav"
            tout = Path(td) / "out.sav"
            tin.write_bytes(data)
            report = _worker_json(
                ["set_coop", "--in", str(tin), "--out", str(tout), "--coop", str(coop_max)]
            )
            return tout.read_bytes(), report

    gvas, magic, save_type = decompress_sav(data)
    ba = bytearray(gvas)
    report: dict = {
        "magic": magic.decode("ascii", errors="replace"),
        "before": {},
        "after": {},
    }
    for key in ("CoopPlayerMaxNum", "ServerPlayerMaxNum", "GuildPlayerMaxNum"):
        report["before"][key] = get_int_property(bytes(ba), key)

    old = set_int_property(ba, "CoopPlayerMaxNum", coop_max)
    if old is None:
        raise ValueError("CoopPlayerMaxNum not found in WorldOption.sav")

    out_magic = magic if keep_format else b"PlZ"
    out_type = save_type if keep_format and magic == b"PlZ" else 0x31
    if out_magic == b"PlM":
        out_type = 0x31
    new_data = compress_sav(bytes(ba), out_magic, out_type)

    # verify
    g2, _, _ = decompress_sav(new_data)
    for key in ("CoopPlayerMaxNum", "ServerPlayerMaxNum", "GuildPlayerMaxNum"):
        report["after"][key] = get_int_property(g2, key)
    return new_data, report


def palooz_available() -> tuple[bool, str]:
    p = _load_palooz()
    if p is not None:
        return True, "Oodle (PlM) ready (in-process)"
    # worker fallback?
    try:
        info = _worker_json(["probe"])
        if info.get("ok"):
            return True, "Oodle (PlM) ready (Python 3.12 worker)"
    except Exception as e:
        return False, f"PlM unavailable: {_palooz_error or e}"
    return False, _palooz_error or "palooz missing"
