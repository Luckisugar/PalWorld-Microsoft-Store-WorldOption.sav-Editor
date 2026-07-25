"""Xbox / Microsoft Store WGS container reader for Palworld."""

from __future__ import annotations

import os
import struct
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)
PALWORLD_PACKAGE = "PocketpairInc.Palworld_ad4psfrxyesvt"
PACKAGES_ROOT = Path(os.path.expandvars(r"%LOCALAPPDATA%\Packages"))


@dataclass
class WgsFile:
    name: str
    path: Path
    size: int
    mtime: datetime


@dataclass
class WgsContainer:
    name: str
    number: int
    files: list[WgsFile] = field(default_factory=list)


@dataclass
class WgsUser:
    user_label: str
    path: Path
    containers: list[WgsContainer] = field(default_factory=list)


def _read_utf16_str(f, str_len: int | None = None) -> str:
    if str_len is None:
        str_len = struct.unpack("<i", f.read(4))[0]
    return f.read(str_len * 2).decode("utf-16").rstrip("\0")


def _read_filetime(f) -> datetime:
    filetime = struct.unpack("<Q", f.read(8))[0]
    return FILETIME_EPOCH + timedelta(seconds=filetime / 10_000_000)


def package_path(package: str = PALWORLD_PACKAGE) -> Path:
    return PACKAGES_ROOT / package


def find_user_dirs(package: str = PALWORLD_PACKAGE) -> list[tuple[str, Path]]:
    wgs_dir = package_path(package) / "SystemAppData" / "wgs"
    if not wgs_dir.is_dir():
        return []

    found: list[tuple[str, Path]] = []
    for entry in wgs_dir.iterdir():
        if not entry.is_dir() or entry.name in {"t"} or "backup" in entry.name.lower():
            continue
        if len(entry.name.split("_")) != 2:
            continue
        user_id_hex, _title = entry.name.split("_", 1)
        try:
            user_id = int(user_id_hex, 16)
            label = str(user_id)
        except ValueError:
            label = entry.name
        found.append((label, entry))
    return found


def read_containers(user_wgs_dir: Path) -> list[WgsContainer]:
    index_path = user_wgs_dir / "containers.index"
    if not index_path.is_file():
        return []

    containers: list[WgsContainer] = []
    with index_path.open("rb") as f:
        f.read(4)
        container_count = struct.unpack("<i", f.read(4))[0]
        _pkg_display = _read_utf16_str(f)
        _store_pkg = _read_utf16_str(f)
        _creation = _read_filetime(f)
        f.read(4)
        _read_utf16_str(f)
        f.read(8)

        for _ in range(container_count):
            container_name = _read_utf16_str(f)
            _read_utf16_str(f)
            _read_utf16_str(f)
            container_num = struct.unpack("B", f.read(1))[0]
            f.read(4)
            container_guid = uuid.UUID(bytes_le=f.read(16))
            _read_filetime(f)
            f.read(16)

            container_path = user_wgs_dir / container_guid.hex.upper()
            container_file_path = container_path / f"container.{container_num}"
            files: list[WgsFile] = []

            if container_file_path.is_file():
                with container_file_path.open("rb") as cf:
                    cf.read(4)
                    file_count = struct.unpack("<i", cf.read(4))[0]
                    for _ in range(file_count):
                        file_name = _read_utf16_str(cf, 64)
                        file_guid = uuid.UUID(bytes_le=cf.read(16))
                        file_guid_2 = uuid.UUID(bytes_le=cf.read(16))

                        candidates = [
                            container_path / file_guid.hex.upper(),
                            container_path / file_guid_2.hex.upper(),
                        ]
                        file_path = next((p for p in candidates if p.is_file()), None)
                        if file_path is None:
                            continue
                        stat = file_path.stat()
                        files.append(
                            WgsFile(
                                name=file_name,
                                path=file_path,
                                size=stat.st_size,
                                mtime=datetime.fromtimestamp(stat.st_mtime),
                            )
                        )

            containers.append(
                WgsContainer(name=container_name, number=container_num, files=files)
            )

    return containers


def palworld_save_entries(containers: list[WgsContainer]) -> list[dict[str, Any]]:
    """Map Palworld WGS containers to relative .sav paths + blob path."""
    entries: list[dict[str, Any]] = []
    for container in containers:
        if not container.files:
            continue
        # Palworld: each "-" is a directory separator; always one Data blob
        rel = container.name.replace("-", "/") + ".sav"
        blob = container.files[0]
        entries.append(
            {
                "rel_path": rel,
                "container_name": container.name,
                "path": blob.path,
                "size": blob.size,
                "mtime": blob.mtime,
            }
        )
    return entries


def is_palworld_installed(package: str = PALWORLD_PACKAGE) -> bool:
    return package_path(package).is_dir()
