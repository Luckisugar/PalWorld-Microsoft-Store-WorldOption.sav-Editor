"""Discover, extract, and patch Palworld MS Store worlds."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import sav, wgs


@dataclass
class WorldInfo:
    world_id: str
    user_label: str
    user_path: Path
    players: list[str] = field(default_factory=list)
    files: dict[str, Path] = field(default_factory=dict)  # rel -> blob path
    level_size: int = 0
    total_size: int = 0
    mtime: datetime | None = None
    coop_max: int | None = None
    server_max: int | None = None
    worldoption_format: str | None = None
    has_worldoption: bool = False
    slot_backups: int = 0
    # From LevelMeta.sav (human-readable)
    world_name: str | None = None
    host_player_name: str | None = None
    host_player_level: int | None = None
    in_game_day: int | None = None

    @property
    def short_id(self) -> str:
        return self.world_id[:8]

    @property
    def player_count(self) -> int:
        return len(self.players)

    @property
    def display_name(self) -> str:
        if self.world_name:
            return self.world_name
        return f"{self.short_id}…"

    @property
    def display_subtitle(self) -> str:
        bits = [f"{self.player_count} player(s)"]
        if self.host_player_name:
            bits.append(f"host {self.host_player_name}")
        if self.host_player_level is not None:
            bits.append(f"Lv.{self.host_player_level}")
        if self.in_game_day is not None:
            bits.append(f"Day {self.in_game_day}")
        return "  ·  ".join(bits)


ROOT_FILES = {"UserOption.sav", "GlobalPalStorage.sav", "GDKBackupTimestamps.sav"}


def _is_world_path(rel: str) -> bool:
    # WorldID/... or WorldID/SlotN/...
    parts = rel.replace("\\", "/").split("/")
    if not parts:
        return False
    wid = parts[0]
    if not re.fullmatch(r"[0-9A-Fa-f]{32}", wid):
        return False
    if parts[-1] in ROOT_FILES and len(parts) == 1:
        return False
    return True


def discover_worlds(package: str = wgs.PALWORLD_PACKAGE) -> list[WorldInfo]:
    if not wgs.is_palworld_installed(package):
        return []

    worlds: dict[tuple[str, str], WorldInfo] = {}

    for user_label, user_path in wgs.find_user_dirs(package):
        containers = wgs.read_containers(user_path)
        entries = wgs.palworld_save_entries(containers)

        for entry in entries:
            rel = entry["rel_path"].replace("\\", "/")
            if rel in ROOT_FILES or not _is_world_path(rel):
                # still allow root-level non-world? skip
                if not re.match(r"^[0-9A-Fa-f]{32}/", rel):
                    continue

            world_id = rel.split("/", 1)[0]
            key = (user_label, world_id)
            if key not in worlds:
                worlds[key] = WorldInfo(
                    world_id=world_id,
                    user_label=user_label,
                    user_path=user_path,
                )
            info = worlds[key]
            info.files[rel] = entry["path"]
            info.total_size += entry["size"]
            mtime: datetime = entry["mtime"]
            if info.mtime is None or mtime > info.mtime:
                info.mtime = mtime

            # players
            m = re.search(r"/Players/([0-9A-Fa-f]{32})\.sav$", rel)
            if m and "/Slot" not in rel:
                pid = m.group(1)
                if pid not in info.players:
                    info.players.append(pid)

            if rel.endswith("/Level/01.sav") and "/Slot" not in rel:
                info.level_size = entry["size"]

            if "/Slot" in rel:
                # count unique slots
                sm = re.search(r"/Slot(\d+)/", rel)
                if sm:
                    info.slot_backups = max(info.slot_backups, int(sm.group(1)))

            if rel.endswith("/WorldOption.sav") and "/Slot" not in rel:
                info.has_worldoption = True
                try:
                    meta = sav.read_worldoption_ints(Path(entry["path"]))
                    info.worldoption_format = meta.get("magic")
                    info.coop_max = meta.get("CoopPlayerMaxNum")
                    info.server_max = meta.get("ServerPlayerMaxNum")
                except Exception:
                    info.worldoption_format = "?"
                    info.coop_max = None

            if rel.endswith("/LevelMeta.sav") and "/Slot" not in rel:
                _fill_level_meta(info, Path(entry["path"]))

    # sort by most recently modified
    result = list(worlds.values())
    result.sort(key=lambda w: w.mtime or datetime.min, reverse=True)
    return result


def _fill_level_meta(info: WorldInfo, path: Path) -> None:
    """Read WorldName / host / day from LevelMeta.sav."""
    try:
        from .worldoption import load_gvas_bytes
        from palworld_save_tools.gvas import GvasFile

        gvas_b, _magic, _st = load_gvas_bytes(path.read_bytes())
        g = GvasFile.read(gvas_b)
        save = g.properties.get("SaveData")
        if not isinstance(save, dict):
            return
        val = save.get("value")
        if not isinstance(val, dict):
            return

        def _scalar(key: str):
            prop = val.get(key)
            if isinstance(prop, dict) and "value" in prop:
                return prop["value"]
            return None

        name = _scalar("WorldName")
        if isinstance(name, str) and name.strip():
            info.world_name = name.strip()
        host = _scalar("HostPlayerName")
        if isinstance(host, str) and host.strip():
            info.host_player_name = host.strip()
        lvl = _scalar("HostPlayerLevel")
        if isinstance(lvl, int):
            info.host_player_level = lvl
        day = _scalar("InGameDay")
        if isinstance(day, int):
            info.in_game_day = day
    except Exception:
        # Keep GUID-only display if meta can't be parsed
        pass


def _level_part_sort_key(path: Path) -> tuple:
    """Sort Level/ pieces: Level.sav first, then 01/02…, then other names."""
    stem = path.stem
    if stem.lower() == "level":
        return (0, 0, stem.lower())
    if stem.isdigit():
        return (1, int(stem), stem.lower())
    return (2, 0, stem.lower())


def _to_steam_sav_bytes(data: bytes) -> tuple[bytes, dict]:
    """
    Make a Game Pass / MS blob safe for Steam + dedicated servers.

    Prefer **CNK strip only** (keeps original PlZ double-zlib headers intact).
    Full decompress/recompress is a fallback and must use correct 0x32 header rules.
    """
    info: dict = {"method": None, "had_cnk": False, "error": None}
    if len(data) >= 24 and data[8:11] == b"CNK":
        info["had_cnk"] = True
        stripped = sav.strip_cnk_wrapper(data)
        # Validate with game-compatible decompress before accepting
        try:
            sav.decompress_sav(stripped)
            info["method"] = "cnk_strip"
            return stripped, info
        except Exception as e:
            info["error"] = f"cnk_strip validate failed: {e}"

    # Already standard PlZ/PlM, or strip failed — try identity if valid
    try:
        sav.decompress_sav(data)
        info["method"] = "identity"
        return data, info
    except Exception as e1:
        info["error"] = f"identity failed: {e1}"

    # Last resort: full restripe with fixed 0x32 compress
    try:
        gvas, magic, save_type = sav.decompress_sav(
            sav.strip_cnk_wrapper(data) if info["had_cnk"] else data
        )
        out_type = save_type if magic == b"PlZ" else 0x31
        out = sav.compress_sav(gvas, magic, out_type)
        sav.decompress_sav(out)  # must round-trip
        info["method"] = "restripe"
        info["error"] = None
        return out, info
    except Exception as e2:
        info["error"] = f"restripe failed: {e2}"
        raise ValueError(info["error"]) from e2


def normalize_steam_world_layout(world_dir: Path) -> dict:
    """
    Turn an extracted MS Store world tree into Steam / dedicated layout.

    MS Store often stores the world as ``Level/Level.sav`` or ``Level/01.sav``.
    Steam + dedicated + Palsitter expect ``Level.sav`` at the world root next to
    ``Players/``, ``LevelMeta.sav``, and optional ``WorldOption.sav``.

    Slot* backups are left alone if present (caller should skip them on extract).
    """
    report: dict = {
        "already_flat": False,
        "parts": 0,
        "level_source": None,
        "method": None,
        "had_cnk": False,
        "rewrapped": False,
        "rewrapped_error": None,
        "level_bytes": 0,
    }

    level_sav = world_dir / "Level.sav"
    level_dir = world_dir / "Level"

    parts: list[Path] = []
    if level_dir.is_dir():
        inner_named = level_dir / "Level.sav"
        if inner_named.is_file():
            parts = [inner_named]
        else:
            parts = sorted(level_dir.glob("*.sav"), key=_level_part_sort_key)

    if not parts and level_sav.is_file():
        report["already_flat"] = True
        parts = [level_sav]
        report["level_source"] = "Level.sav"
    elif parts:
        report["level_source"] = ", ".join(p.name for p in parts)
    else:
        raise FileNotFoundError(
            f"Steam-style export needs Level.sav or Level/*.sav under:\n{world_dir}"
        )

    if len(parts) == 1:
        data = parts[0].read_bytes()
    else:
        # Multi-chunk Game Pass: join in sort order
        data = b"".join(p.read_bytes() for p in parts)

    report["parts"] = len(parts)

    try:
        data, conv = _to_steam_sav_bytes(data)
        report["method"] = conv.get("method")
        report["had_cnk"] = bool(conv.get("had_cnk"))
        report["rewrapped"] = conv.get("method") in ("cnk_strip", "restripe")
        if conv.get("error"):
            report["rewrapped_error"] = conv["error"]
    except Exception as e:
        report["rewrapped_error"] = str(e)
        raise

    level_sav.write_bytes(data)
    report["level_bytes"] = len(data)

    # Remove nested Level/ so the tree matches Steam SaveGames layout
    if level_dir.is_dir():
        shutil.rmtree(level_dir, ignore_errors=True)

    return report


def extract_world(
    info: WorldInfo,
    dest_dir: Path,
    *,
    include_slots: bool = True,
    steam_style: bool = False,
) -> Path:
    """
    Extract one world to dest_dir/world_id/ ... returns folder path.

    steam_style=True:
      - skips Slot* backups (dedicated / Steam host save does not use them)
      - flattens Level/* → Level.sav at world root (Palsitter / dedicated import)
    """
    if steam_style:
        include_slots = False

    out = dest_dir / info.world_id
    out.mkdir(parents=True, exist_ok=True)

    for rel, blob in info.files.items():
        rel_n = rel.replace("\\", "/")
        if not include_slots and "/Slot" in rel_n:
            continue
        # strip world_id prefix for cleaner tree inside folder
        inner = rel_n.split("/", 1)[1] if rel_n.startswith(info.world_id + "/") else rel_n
        target = out / inner
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(blob, target)

    if steam_style:
        report = normalize_steam_world_layout(out)
        # stash for callers / logging via a side-car text file (tiny, optional)
        try:
            lines = [
                "steam_style_export=1",
                f"parts={report.get('parts')}",
                f"level_source={report.get('level_source')}",
                f"rewrapped={report.get('rewrapped')}",
                f"level_bytes={report.get('level_bytes')}",
            ]
            if report.get("rewrapped_error"):
                lines.append(f"rewrapped_error={report['rewrapped_error']}")
            (out / ".palsitter-steam-export.txt").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )
        except Exception:
            pass
        # attach for Python callers
        extract_world.last_steam_report = report  # type: ignore[attr-defined]

    return out


def extract_all_files(
    package: str,
    dest_dir: Path,
    user_label: str | None = None,
) -> Path:
    """Extract entire account save tree (all worlds)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for label, user_path in wgs.find_user_dirs(package):
        if user_label is not None and label != user_label:
            continue
        containers = wgs.read_containers(user_path)
        for entry in wgs.palworld_save_entries(containers):
            rel = entry["rel_path"].replace("\\", "/")
            target = dest_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry["path"], target)
    return dest_dir


def backup_file(path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"{path.name}.bak_{stamp}"
    shutil.copy2(path, dest)
    return dest


def set_coop_max(
    info: WorldInfo,
    coop_max: int,
    backup_dir: Path,
) -> dict:
    """Patch live WGS WorldOption for this world. Game must be closed."""
    rel = f"{info.world_id}/WorldOption.sav"
    blob = info.files.get(rel)
    if blob is None:
        # try find any
        for r, p in info.files.items():
            if r.endswith("WorldOption.sav") and "/Slot" not in r:
                blob = p
                rel = r
                break
    if blob is None:
        raise FileNotFoundError("WorldOption.sav not found for this world")

    data = Path(blob).read_bytes()
    bak = backup_file(Path(blob), backup_dir)
    new_data, report = sav.edit_worldoption_coop(data, coop_max)
    Path(blob).write_bytes(new_data)
    report["backup"] = str(bak)
    report["blob"] = str(blob)
    report["rel"] = rel
    # refresh cached fields
    info.coop_max = report["after"].get("CoopPlayerMaxNum")
    info.server_max = report["after"].get("ServerPlayerMaxNum")
    return report


def palworld_running() -> bool:
    try:
        import subprocess

        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq Palworld-WinGDK-Shipping.exe"],
            text=True,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "Palworld-WinGDK-Shipping.exe" in out
    except Exception:
        return False
