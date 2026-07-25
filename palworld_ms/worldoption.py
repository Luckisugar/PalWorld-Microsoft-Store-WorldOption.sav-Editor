"""Load / edit / save Palworld WorldOption.sav (PlZ + PlM)."""

from __future__ import annotations

import copy
import json
import struct
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from palworld_save_tools.gvas import GvasFile

from . import sav


@dataclass
class SettingField:
    name: str
    prop_type: str  # IntProperty, FloatProperty, ...
    value: Any
    raw: dict  # original property dict for write-back
    group: str = "Settings"  # Settings | Root

    @property
    def display_type(self) -> str:
        return self.prop_type.replace("Property", "")


def _parse_header_magic(data: bytes) -> bytes:
    return data[8:11]


def load_gvas_bytes(sav_data: bytes) -> tuple[bytes, bytes, int]:
    """Return (gvas_bytes, magic, save_type). Uses 3.12 worker for PlM if needed."""
    magic = _parse_header_magic(sav_data)
    if magic == b"PlM" and sav._load_palooz() is None:
        with tempfile.TemporaryDirectory() as td:
            tin = Path(td) / "in.sav"
            tout = Path(td) / "out.gvas"
            tin.write_bytes(sav_data)
            info = sav._worker_json(["dump_gvas", "--in", str(tin), "--out", str(tout)])
            return tout.read_bytes(), magic, int(info.get("save_type", 0x31))
    return sav.decompress_sav(sav_data)


def pack_gvas_bytes(gvas: bytes, magic: bytes, save_type: int = 0x31) -> bytes:
    if magic == b"PlM" and sav._load_palooz() is None:
        with tempfile.TemporaryDirectory() as td:
            tin = Path(td) / "in.gvas"
            tout = Path(td) / "out.sav"
            tin.write_bytes(gvas)
            sav._worker_json(
                [
                    "pack_gvas",
                    "--in",
                    str(tin),
                    "--out",
                    str(tout),
                    "--magic",
                    magic.decode("ascii"),
                    "--save-type",
                    str(save_type),
                ]
            )
            return tout.read_bytes()
    return sav.compress_sav(gvas, magic, save_type)


def extract_fields(gvas_file: GvasFile) -> list[SettingField]:
    fields: list[SettingField] = []

    # Root scalars (Version etc.) — skip complex Timestamp/OptionWorldData wrappers
    for name, prop in gvas_file.properties.items():
        if name in ("OptionWorldData", "Timestamp"):
            continue
        if not isinstance(prop, dict) or "type" not in prop:
            continue
        fields.append(
            SettingField(
                name=name,
                prop_type=prop["type"],
                value=_readable_value(prop),
                raw=prop,
                group="Root",
            )
        )

    try:
        settings = gvas_file.properties["OptionWorldData"]["value"]["Settings"]["value"]
    except (KeyError, TypeError):
        return fields

    for name, prop in settings.items():
        if not isinstance(prop, dict) or "type" not in prop:
            continue
        fields.append(
            SettingField(
                name=name,
                prop_type=prop["type"],
                value=_readable_value(prop),
                raw=prop,
                group="Settings",
            )
        )
    return fields


def _readable_value(prop: dict) -> Any:
    t = prop.get("type", "")
    v = prop.get("value")
    if t == "EnumProperty" and isinstance(v, dict):
        return v.get("value", "")
    if t == "ArrayProperty" and isinstance(v, dict):
        return v.get("values", [])
    if t == "NameProperty":
        return v
    return v


def apply_field_value(field: SettingField, new_value: Any) -> None:
    """Mutate field.raw in place from a UI-friendly value."""
    t = field.prop_type
    if t == "IntProperty":
        field.raw["value"] = int(new_value)
    elif t == "FloatProperty":
        field.raw["value"] = float(new_value)
    elif t == "BoolProperty":
        if isinstance(new_value, str):
            field.raw["value"] = new_value.strip().lower() in ("1", "true", "yes", "on")
        else:
            field.raw["value"] = bool(new_value)
    elif t == "StrProperty":
        field.raw["value"] = str(new_value)
    elif t == "NameProperty":
        field.raw["value"] = str(new_value)
    elif t == "EnumProperty":
        # keep enum type, replace value string
        if isinstance(field.raw.get("value"), dict):
            field.raw["value"]["value"] = str(new_value)
        else:
            field.raw["value"] = str(new_value)
    elif t == "ArrayProperty":
        if isinstance(new_value, str):
            new_value = json.loads(new_value) if new_value.strip() else []
        if not isinstance(new_value, list):
            raise ValueError("Array must be a JSON list")
        if isinstance(field.raw.get("value"), dict):
            field.raw["value"]["values"] = new_value
        else:
            field.raw["value"] = {"values": new_value}
    else:
        raise ValueError(f"Unsupported type for edit: {t}")
    field.value = _readable_value(field.raw)


@dataclass
class WorldOptionDoc:
    path: Path
    sav_data: bytes
    magic: bytes
    save_type: int
    gvas_file: GvasFile
    fields: list[SettingField]
    original_gvas: bytes

    def field_map(self) -> dict[str, SettingField]:
        return {f.name: f for f in self.fields}

    def apply_changes(self, changes: dict[str, Any]) -> list[str]:
        """Apply {name: new_value}. Returns list of changed names."""
        changed: list[str] = []
        fmap = self.field_map()
        for name, val in changes.items():
            f = fmap.get(name)
            if f is None:
                continue
            old = f.value
            apply_field_value(f, val)
            if f.value != old:
                changed.append(name)
        return changed

    def build_sav(self) -> bytes:
        gvas_out = self.gvas_file.write()
        return pack_gvas_bytes(gvas_out, self.magic, self.save_type)


def load_worldoption(path: Path) -> WorldOptionDoc:
    data = path.read_bytes()
    gvas_bytes, magic, save_type = load_gvas_bytes(data)
    gvas_file = GvasFile.read(gvas_bytes)
    fields = extract_fields(gvas_file)
    return WorldOptionDoc(
        path=path,
        sav_data=data,
        magic=magic,
        save_type=save_type,
        gvas_file=gvas_file,
        fields=fields,
        original_gvas=gvas_bytes,
    )


def save_worldoption(doc: WorldOptionDoc, dest: Path | None = None) -> Path:
    out = doc.build_sav()
    target = dest or doc.path
    target.write_bytes(out)
    return target


# Known enum choices for nicer UI (optional)
ENUM_CHOICES: dict[str, list[str]] = {
    "Difficulty": [
        "EPalOptionWorldDifficulty::None",
        "EPalOptionWorldDifficulty::Easy",
        "EPalOptionWorldDifficulty::Normal",
        "EPalOptionWorldDifficulty::Hard",
        "EPalOptionWorldDifficulty::Custom",
    ],
    "DeathPenalty": [
        "EPalOptionWorldDeathPenalty::None",
        "EPalOptionWorldDeathPenalty::Item",
        "EPalOptionWorldDeathPenalty::ItemAndEquipment",
        "EPalOptionWorldDeathPenalty::All",
    ],
    "RandomizerType": [
        "EPalRandomizerType::None",
        "EPalRandomizerType::Region",
        "EPalRandomizerType::All",
    ],
    "LogFormatType": [
        "EPalLogFormatType::Text",
        "EPalLogFormatType::Json",
    ],
}
