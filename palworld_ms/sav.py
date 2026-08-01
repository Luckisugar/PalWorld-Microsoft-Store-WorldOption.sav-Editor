"""Palworld .sav compress/decompress and WorldOption int edits."""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path

from . import runtime

# Optional Oodle (PlM) via vendor palooz
_palooz = None
_palooz_error: str | None = None
_TOOL_ROOT = Path(__file__).resolve().parent.parent


def _find_py312() -> Path | None:
    return runtime.find_py312()


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
        target = runtime.appdata_runtime_dir()
        raise RuntimeError(
            "PlM (Oodle) saves need a small Python 3.12 helper + palooz.\n\n"
            "In the tool, click:  Install PlM support\n"
            f"(installs official Python into:\n{target})"
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
    """
    Decompress a Palworld .sav blob to raw GVAS.

    PlZ save_type 0x32 is *double* zlib. The header ``compressed_len`` field is the
    size after the *first* decompress (inner), while the on-disk payload is the outer
    wrap — same contract as palworld-save-tools / the game.
    """
    unc, cmp, magic, save_type, offset = parse_header(data)
    if magic == b"PlZ":
        # Decompress all bytes after the header (not a cmp-sized slice). For 0x32 the
        # first pass yields a buffer whose length must equal the header cmp field.
        out = zlib.decompress(data[offset:])
        if save_type == 0x32:
            if len(out) != cmp:
                raise ValueError(
                    f"PlZ 0x32 inner size mismatch: {len(out)} != header cmp {cmp}"
                )
            out = zlib.decompress(out)
        elif save_type == 0x31:
            if cmp != len(data) - offset and len(out) != unc:
                # tolerate minor header quirks if GVAS size matches
                pass
        elif save_type == 0x30:
            pass
        else:
            raise ValueError(f"Unhandled PlZ save_type: {save_type:#x}")
    elif magic == b"PlM":
        payload = data[offset : offset + cmp] if cmp else data[offset:]
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
    """
    Compress GVAS to a .sav blob.

    For PlZ 0x32, the header ``compressed_len`` is the *inner* zlib size; the file
    body is zlib(zlib(gvas)). Writing the outer size there makes PalServer report
    \"Save data is corrupted\".
    """
    if magic == b"PlZ":
        inner = zlib.compress(gvas)
        compressed_len = len(inner)
        if save_type == 0x32:
            payload = zlib.compress(inner)
        else:
            # 0x30 / 0x31: single zlib; header cmp == payload size
            payload = inner
            save_type = 0x31 if save_type not in (0x30, 0x31, 0x32) else save_type
            if save_type == 0x30:
                save_type = 0x31
            compressed_len = len(payload)
    elif magic == b"PlM":
        palooz = _load_palooz()
        if palooz is None:
            raise RuntimeError(_palooz_error or "palooz missing")
        # Kraken=8, Normal=4
        payload = palooz.compress(8, 4, gvas, len(gvas))
        if not payload:
            raise RuntimeError("palooz compress returned empty")
        compressed_len = len(payload)
        save_type = 0x31
    else:
        raise ValueError(f"Unknown magic {magic!r}")
    return (
        len(gvas).to_bytes(4, "little")
        + compressed_len.to_bytes(4, "little")
        + magic
        + bytes([save_type])
        + payload
    )


def strip_cnk_wrapper(data: bytes) -> bytes:
    """If the blob is CNK-wrapped (Game Pass), return the inner PlZ/PlM .sav bytes."""
    if len(data) >= 24 and data[8:11] == b"CNK":
        return data[12:]
    return data


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
    st = runtime.runtime_status()
    if st["ready"] and st["python"]:
        try:
            info = _worker_json(["probe"])
            if info.get("ok"):
                return True, f"Oodle (PlM) ready · {st['python']}"
        except Exception as e:
            return False, f"PlM worker failed: {e}"
    # Try probe only if python exists
    py = _find_py312()
    if py is not None:
        try:
            info = _worker_json(["probe"])
            if info.get("ok"):
                return True, f"Oodle (PlM) ready · {py}"
        except Exception as e:
            return False, f"PlM unavailable: {e}"
    return False, st["detail"] or (_palooz_error or "palooz missing")
