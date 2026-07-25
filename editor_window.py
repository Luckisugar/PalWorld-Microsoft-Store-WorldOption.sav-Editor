"""WorldOption.sav full editor window with search."""

from __future__ import annotations

import json
from pathlib import Path
from tkinter import messagebox
from typing import Any, Callable

import customtkinter as ctk

from palworld_ms import worlds
from palworld_ms.worldoption import (
    ENUM_CHOICES,
    SettingField,
    WorldOptionDoc,
    load_worldoption,
    save_worldoption,
)
from palworld_ms.worlds import WorldInfo

# match main app theme
BG = "#0f1117"
CARD = "#171b24"
ROW = "#12161f"
ROW_ALT = "#151a24"
ACCENT = "#5b8def"
ACCENT_DIM = "#3d5f9e"
GREEN = "#3dd68c"
ORANGE = "#f0a04b"
RED = "#f07178"
MUTED = "#8b93a7"
TEXT = "#e8ecf4"
TYPE_COLORS = {
    "Int": "#7aa2f7",
    "Float": "#bb9af7",
    "Bool": "#9ece6a",
    "Str": "#e0af68",
    "Enum": "#f7768e",
    "Array": "#73daca",
    "Name": "#ff9e64",
}


class PropertyRow(ctk.CTkFrame):
    def __init__(
        self,
        master,
        field: SettingField,
        on_change: Callable[[str, Any], None],
        **kwargs,
    ):
        super().__init__(master, fg_color=ROW, corner_radius=8, **kwargs)
        self.field = field
        self.on_change = on_change
        self._build()

    def _build(self):
        self.grid_columnconfigure(2, weight=1)

        # type badge
        short = self.field.display_type
        color = TYPE_COLORS.get(short, MUTED)
        badge = ctk.CTkLabel(
            self,
            text=short[:5],
            width=48,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=color,
            fg_color="#1a1f2c",
            corner_radius=6,
        )
        badge.grid(row=0, column=0, padx=(10, 8), pady=8)

        name = ctk.CTkLabel(
            self,
            text=self.field.name,
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=TEXT,
            anchor="w",
            width=280,
        )
        name.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=8)

        editor = self._make_editor()
        editor.grid(row=0, column=2, sticky="ew", padx=(0, 12), pady=8)
        self.editor = editor

    def _make_editor(self):
        f = self.field
        t = f.prop_type

        if t == "BoolProperty":
            var = ctk.BooleanVar(value=bool(f.value))
            sw = ctk.CTkSwitch(
                self,
                text="On" if f.value else "Off",
                variable=var,
                command=lambda: self._bool_changed(var, sw),
                progress_color=GREEN,
                button_color="#c8d0e0",
                fg_color="#2a3142",
            )
            sw._var = var  # type: ignore
            return sw

        if t == "EnumProperty" and f.name in ENUM_CHOICES:
            choices = list(ENUM_CHOICES[f.name])
            cur = str(f.value)
            if cur not in choices:
                choices = [cur] + choices
            box = ctk.CTkComboBox(
                self,
                values=choices,
                command=lambda v: self.on_change(f.name, v),
                height=30,
                corner_radius=6,
                border_color="#2a3142",
                button_color=ACCENT,
                dropdown_fg_color=CARD,
            )
            box.set(cur)
            box._is_combo = True  # type: ignore
            return box

        if t == "ArrayProperty":
            text = json.dumps(f.value if f.value is not None else [], ensure_ascii=False)
            entry = ctk.CTkEntry(self, height=30, corner_radius=6, border_color="#2a3142")
            entry.insert(0, text)
            entry.bind("<FocusOut>", lambda _e: self._entry_commit(entry))
            entry.bind("<Return>", lambda _e: self._entry_commit(entry))
            entry._is_array = True  # type: ignore
            return entry

        # Int / Float / Str / Name / Enum freeform
        entry = ctk.CTkEntry(self, height=30, corner_radius=6, border_color="#2a3142")
        val = f.value
        if isinstance(val, float):
            # trim ugly binary float noise for display
            s = f"{val:.6g}"
        else:
            s = "" if val is None else str(val)
        entry.insert(0, s)
        entry.bind("<FocusOut>", lambda _e: self._entry_commit(entry))
        entry.bind("<Return>", lambda _e: self._entry_commit(entry))
        return entry

    def _bool_changed(self, var: ctk.BooleanVar, sw: ctk.CTkSwitch):
        v = bool(var.get())
        sw.configure(text="On" if v else "Off")
        self.on_change(self.field.name, v)

    def _entry_commit(self, entry: ctk.CTkEntry):
        raw = entry.get()
        t = self.field.prop_type
        try:
            if t == "IntProperty":
                val: Any = int(float(raw))  # allow "10.0"
            elif t == "FloatProperty":
                val = float(raw)
            elif t == "ArrayProperty":
                val = json.loads(raw) if raw.strip() else []
            else:
                val = raw
            self.on_change(self.field.name, val)
            entry.configure(border_color="#2a3142")
        except Exception:
            entry.configure(border_color=RED)

    def matches(self, query: str) -> bool:
        q = query.lower().strip()
        if not q:
            return True
        blob = f"{self.field.name} {self.field.display_type} {self.field.value}".lower()
        return q in blob

    def set_visible(self, yes: bool):
        # packing is managed by parent filter pass
        if not yes and self.winfo_ismapped():
            self.pack_forget()


class WorldOptionEditor(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        info: WorldInfo,
        backup_dir: Path,
        on_saved: Callable[[], None] | None = None,
    ):
        super().__init__(master)
        self.info = info
        self.backup_dir = backup_dir
        self.on_saved = on_saved
        self.doc: WorldOptionDoc | None = None
        self.pending: dict[str, Any] = {}
        self.rows: list[PropertyRow] = []

        self.title(f"Edit WorldOption — {info.display_name}")
        self.geometry("920x700")
        self.minsize(760, 520)
        self.configure(fg_color=BG)
        self.transient(master)
        self.grab_set()

        self._build_chrome()
        self.after(50, self._load)

    def _build_chrome(self):
        # header
        header = ctk.CTkFrame(self, fg_color=BG)
        header.pack(fill="x", padx=18, pady=(16, 8))

        ctk.CTkLabel(
            header,
            text="WorldOption.sav",
            font=ctk.CTkFont(family="Segoe UI Semibold", size=20),
            text_color=TEXT,
        ).pack(side="left")

        self.meta_lbl = ctk.CTkLabel(
            header,
            text=f"{self.info.display_name}  ·  loading…",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
        )
        self.meta_lbl.pack(side="left", padx=14)

        self.status_lbl = ctk.CTkLabel(
            header, text="", font=ctk.CTkFont(size=12), text_color=MUTED
        )
        self.status_lbl.pack(side="right")

        # search bar
        search_bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        search_bar.pack(fill="x", padx=18, pady=(4, 8))

        ctk.CTkLabel(
            search_bar, text="Search", text_color=MUTED, font=ctk.CTkFont(size=12)
        ).pack(side="left", padx=(14, 8), pady=10)

        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._filter())
        self.search_entry = ctk.CTkEntry(
            search_bar,
            textvariable=self.search_var,
            placeholder_text="Filter by name, type, or value…  e.g. Coop, ExpRate, bool",
            height=34,
            corner_radius=8,
            border_color="#2a3142",
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=10)

        self.count_lbl = ctk.CTkLabel(
            search_bar, text="", width=90, text_color=MUTED, font=ctk.CTkFont(size=12)
        )
        self.count_lbl.pack(side="right", padx=(0, 14))

        # list
        self.list_frame = ctk.CTkScrollableFrame(
            self, fg_color=CARD, corner_radius=12
        )
        self.list_frame.pack(fill="both", expand=True, padx=18, pady=(0, 8))

        # footer actions
        foot = ctk.CTkFrame(self, fg_color=BG)
        foot.pack(fill="x", padx=18, pady=(4, 16))

        ctk.CTkButton(
            foot,
            text="Cancel",
            width=100,
            height=36,
            corner_radius=8,
            fg_color="#2a3142",
            hover_color="#353e52",
            command=self.destroy,
        ).pack(side="left")

        ctk.CTkButton(
            foot,
            text="Reset changes",
            width=120,
            height=36,
            corner_radius=8,
            fg_color="transparent",
            border_width=1,
            border_color="#2a3142",
            hover_color="#1a1f2a",
            command=self._reset,
        ).pack(side="left", padx=8)

        self.save_btn = ctk.CTkButton(
            foot,
            text="Save to live save",
            width=160,
            height=36,
            corner_radius=8,
            fg_color=GREEN,
            hover_color="#2bb573",
            text_color="#0a1210",
            font=ctk.CTkFont(weight="bold"),
            command=self._save,
        )
        self.save_btn.pack(side="right")

        self.dirty_lbl = ctk.CTkLabel(
            foot, text="", text_color=ORANGE, font=ctk.CTkFont(size=12)
        )
        self.dirty_lbl.pack(side="right", padx=12)

    def _load(self):
        try:
            rel = f"{self.info.world_id}/WorldOption.sav"
            blob = self.info.files.get(rel)
            if blob is None:
                for r, p in self.info.files.items():
                    if r.endswith("WorldOption.sav") and "/Slot" not in r:
                        blob = p
                        break
            if blob is None:
                raise FileNotFoundError("WorldOption.sav not found for this world")

            self.doc = load_worldoption(Path(blob))
            magic = self.doc.magic.decode("ascii", errors="replace")
            self.meta_lbl.configure(
                text=(
                    f"{self.info.display_name}  ·  {len(self.doc.fields)} settings  ·  "
                    f"{magic}  ·  ID {self.info.short_id}…"
                )
            )
            self._build_rows()
            self.status_lbl.configure(text="Loaded", text_color=GREEN)
            self.search_entry.focus_set()
        except Exception as e:
            self.status_lbl.configure(text="Failed", text_color=RED)
            messagebox.showerror("Load failed", str(e), parent=self)
            self.destroy()

    def _build_rows(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self.rows.clear()
        if not self.doc:
            return

        # Settings first (gameplay), then Root
        for group in ("Settings", "Root"):
            for field in (f for f in self.doc.fields if f.group == group):
                row = PropertyRow(
                    self.list_frame, field, on_change=self._on_change
                )
                row._group = group  # type: ignore
                self.rows.append(row)
        self._filter()

    def _on_change(self, name: str, value: Any):
        self.pending[name] = value
        n = len(self.pending)
        self.dirty_lbl.configure(
            text=f"{n} unsaved change{'s' if n != 1 else ''}" if n else ""
        )

    def _filter(self):
        q = self.search_var.get()
        # hide all rows first, then re-pack matches in original order
        for row in self.rows:
            row.pack_forget()
        visible = 0
        last_group = None
        # destroy old dynamic group labels if any — rebuild simple: only rows
        for child in list(self.list_frame.winfo_children()):
            if getattr(child, "_is_group_hdr", False):
                child.destroy()

        for row in self.rows:
            if not row.matches(q):
                continue
            group = getattr(row, "_group", "")
            if group and group != last_group:
                hdr = ctk.CTkLabel(
                    self.list_frame,
                    text=group.upper(),
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=MUTED,
                    anchor="w",
                )
                hdr._is_group_hdr = True  # type: ignore
                hdr.pack(fill="x", padx=10, pady=(12, 4))
                last_group = group
            row.pack(fill="x", padx=6, pady=3)
            visible += 1
        self.count_lbl.configure(text=f"{visible} / {len(self.rows)}")

    def _reset(self):
        if not self.doc:
            return
        self.pending.clear()
        self.dirty_lbl.configure(text="")
        # reload from original path
        self.doc = load_worldoption(self.doc.path)
        self._build_rows()
        self.status_lbl.configure(text="Reset", text_color=MUTED)

    def _save(self):
        if not self.doc:
            return
        if not self.pending:
            messagebox.showinfo("Nothing to save", "No changes yet.", parent=self)
            return

        if worlds.palworld_running():
            messagebox.showwarning(
                "Game is running",
                "Close Palworld completely before saving,\n"
                "or it will overwrite your edits.",
                parent=self,
            )
            return

        # validate by applying to a working copy first
        try:
            # re-load fresh doc so we don't double-apply
            doc = load_worldoption(self.doc.path)
            changed = doc.apply_changes(self.pending)
            if not changed:
                messagebox.showinfo("No changes", "Values match existing save.", parent=self)
                return
        except Exception as e:
            messagebox.showerror("Invalid value", str(e), parent=self)
            return

        if not messagebox.askyesno(
            "Save WorldOption",
            f"Write {len(changed)} change(s) to live MS Store save?\n\n"
            + ", ".join(changed[:12])
            + ("…" if len(changed) > 12 else "")
            + "\n\nAuto-backup will be created.",
            parent=self,
        ):
            return

        try:
            bak = worlds.backup_file(doc.path, self.backup_dir)
            save_worldoption(doc)
            # refresh in-memory
            self.doc = load_worldoption(doc.path)
            self.pending.clear()
            self.dirty_lbl.configure(text="")
            self._build_rows()
            self.status_lbl.configure(text="Saved", text_color=GREEN)

            # update WorldInfo cache if coop present
            coop = next(
                (f.value for f in self.doc.fields if f.name == "CoopPlayerMaxNum"),
                None,
            )
            if coop is not None:
                self.info.coop_max = int(coop)
            srv = next(
                (f.value for f in self.doc.fields if f.name == "ServerPlayerMaxNum"),
                None,
            )
            if srv is not None:
                self.info.server_max = int(srv)
            self.info.worldoption_format = self.doc.magic.decode("ascii", errors="replace")

            if self.on_saved:
                self.on_saved()

            messagebox.showinfo(
                "Saved",
                f"Updated {len(changed)} setting(s).\nBackup:\n{bak}",
                parent=self,
            )
        except Exception as e:
            messagebox.showerror("Save failed", str(e), parent=self)
