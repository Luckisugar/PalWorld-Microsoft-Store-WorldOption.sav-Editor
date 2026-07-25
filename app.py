#!/usr/bin/env python3
"""Palworld MS Store Toolkit — unpack worlds, edit co-op max players."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

# Ensure local package + vendor are importable
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

import customtkinter as ctk

from palworld_ms import __version__, sav, wgs, worlds
from palworld_ms.worlds import WorldInfo
from editor_window import WorldOptionEditor

# ── theme ──────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

BG = "#0f1117"
CARD = "#171b24"
CARD_HOVER = "#1e2430"
CARD_SEL = "#243044"
ACCENT = "#5b8def"
ACCENT_DIM = "#3d5f9e"
GREEN = "#3dd68c"
ORANGE = "#f0a04b"
RED = "#f07178"
MUTED = "#8b93a7"
TEXT = "#e8ecf4"

EXPORTS = ROOT / "exports"
BACKUPS = ROOT / "backups"


def _fmt_size(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    if n >= 1_000:
        return f"{n / 1_000:.1f} KB"
    return f"{n} B"


def _fmt_time(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return dt.strftime("%Y-%m-%d  %H:%M")


class WorldCard(ctk.CTkFrame):
    def __init__(self, master, info: WorldInfo, on_select, **kwargs):
        super().__init__(master, fg_color=CARD, corner_radius=12, **kwargs)
        self.info = info
        self.on_select = on_select
        self.selected = False

        self.configure(cursor="hand2")
        self.bind("<Button-1>", self._click)
        for w in self._build():
            w.bind("<Button-1>", self._click)

    def _build(self):
        widgets = []
        pad = ctk.CTkFrame(self, fg_color="transparent")
        pad.pack(fill="x", padx=14, pady=12)
        widgets.append(pad)

        top = ctk.CTkFrame(pad, fg_color="transparent")
        top.pack(fill="x")
        widgets.append(top)

        title = ctk.CTkLabel(
            top,
            text=self.info.short_id.upper() + "…",
            font=ctk.CTkFont(family="Segoe UI Semibold", size=15),
            text_color=TEXT,
            anchor="w",
        )
        title.pack(side="left")
        widgets.append(title)

        badge_txt = f"{self.info.player_count}p"
        if self.info.coop_max is not None:
            badge_txt += f"  ·  max {self.info.coop_max}"
        badge = ctk.CTkLabel(
            top,
            text=badge_txt,
            font=ctk.CTkFont(size=12),
            text_color=ACCENT,
            fg_color="#1a2740",
            corner_radius=8,
            padx=8,
            pady=2,
        )
        badge.pack(side="right")
        widgets.append(badge)

        meta = ctk.CTkLabel(
            pad,
            text=(
                f"Level {_fmt_size(self.info.level_size)}  ·  "
                f"Total {_fmt_size(self.info.total_size)}  ·  "
                f"{_fmt_time(self.info.mtime)}"
            ),
            font=ctk.CTkFont(size=11),
            text_color=MUTED,
            anchor="w",
        )
        meta.pack(fill="x", pady=(6, 0))
        widgets.append(meta)

        fmt = self.info.worldoption_format or "—"
        sub = ctk.CTkLabel(
            pad,
            text=f"ID {self.info.world_id}   ·   WorldOption {fmt}",
            font=ctk.CTkFont(size=10),
            text_color="#5c6478",
            anchor="w",
        )
        sub.pack(fill="x", pady=(2, 0))
        widgets.append(sub)
        return widgets

    def _click(self, _event=None):
        self.on_select(self.info)

    def set_selected(self, yes: bool):
        self.selected = yes
        self.configure(fg_color=CARD_SEL if yes else CARD)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"Palworld MS Toolkit  v{__version__}")
        self.geometry("980x680")
        self.minsize(860, 560)
        self.configure(fg_color=BG)

        self.worlds: list[WorldInfo] = []
        self.cards: list[WorldCard] = []
        self.selected: WorldInfo | None = None
        self._busy = False

        self._build_ui()
        self.after(120, self.scan)

    # ── layout ────────────────────────────────────────────────────────────
    def _build_ui(self):
        # header
        header = ctk.CTkFrame(self, fg_color=BG, height=72)
        header.pack(fill="x", padx=22, pady=(18, 8))
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text="Palworld  MS Store Toolkit",
            font=ctk.CTkFont(family="Segoe UI Semibold", size=22),
            text_color=TEXT,
        ).pack(side="left", pady=12)

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right", pady=12)

        self.status_dot = ctk.CTkLabel(
            right, text="●", font=ctk.CTkFont(size=14), text_color=MUTED, width=18
        )
        self.status_dot.pack(side="left", padx=(0, 6))
        self.status_lbl = ctk.CTkLabel(
            right, text="Ready", font=ctk.CTkFont(size=12), text_color=MUTED
        )
        self.status_lbl.pack(side="left", padx=(0, 14))

        self.scan_btn = ctk.CTkButton(
            right,
            text="Scan saves",
            width=110,
            height=34,
            corner_radius=8,
            fg_color=ACCENT,
            hover_color=ACCENT_DIM,
            command=self.scan,
        )
        self.scan_btn.pack(side="left")

        # body
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=(4, 10))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        # left: world list
        left = ctk.CTkFrame(body, fg_color=CARD, corner_radius=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            left,
            text="WORLD SAVES",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=MUTED,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))

        self.list_frame = ctk.CTkScrollableFrame(
            left, fg_color="transparent", corner_radius=0
        )
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 10))

        # right: detail + actions
        right_col = ctk.CTkFrame(body, fg_color=CARD, corner_radius=14)
        right_col.grid(row=0, column=1, sticky="nsew")

        ctk.CTkLabel(
            right_col,
            text="SELECTED WORLD",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=MUTED,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(14, 4))

        self.detail = ctk.CTkLabel(
            right_col,
            text="Select a world from the list.",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
            justify="left",
            anchor="nw",
        )
        self.detail.pack(fill="x", padx=16, pady=(4, 12))

        # primary editor action
        self.edit_btn = ctk.CTkButton(
            right_col,
            text="Edit WorldOption.sav",
            height=40,
            corner_radius=10,
            fg_color=GREEN,
            hover_color="#2bb573",
            text_color="#0a1210",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.open_worldoption_editor,
        )
        self.edit_btn.pack(fill="x", padx=14, pady=(0, 10))

        # action buttons
        actions = ctk.CTkFrame(right_col, fg_color="transparent")
        actions.pack(fill="x", padx=14, pady=(4, 8))

        self.extract_btn = ctk.CTkButton(
            actions,
            text="Extract world",
            height=36,
            corner_radius=8,
            fg_color=ACCENT,
            hover_color=ACCENT_DIM,
            command=self.extract_selected,
        )
        self.extract_btn.pack(fill="x", pady=4)

        self.extract_all_btn = ctk.CTkButton(
            actions,
            text="Extract all worlds",
            height=36,
            corner_radius=8,
            fg_color="#2a3142",
            hover_color="#353e52",
            command=self.extract_all,
        )
        self.extract_all_btn.pack(fill="x", pady=4)

        self.open_exports_btn = ctk.CTkButton(
            actions,
            text="Open exports folder",
            height=34,
            corner_radius=8,
            fg_color="transparent",
            border_width=1,
            border_color="#2a3142",
            hover_color="#1a1f2a",
            command=lambda: self._open_path(EXPORTS),
        )
        self.open_exports_btn.pack(fill="x", pady=4)

        self.open_wgs_btn = ctk.CTkButton(
            actions,
            text="Open WGS folder",
            height=34,
            corner_radius=8,
            fg_color="transparent",
            border_width=1,
            border_color="#2a3142",
            hover_color="#1a1f2a",
            command=self._open_wgs,
        )
        self.open_wgs_btn.pack(fill="x", pady=4)

        warn = ctk.CTkLabel(
            right_col,
            text=(
                "Close Palworld before saving WorldOption.\n"
                "Auto-backup is created every time."
            ),
            font=ctk.CTkFont(size=11),
            text_color="#6a7388",
            justify="left",
        )
        warn.pack(fill="x", padx=16, pady=(8, 4))

        # log
        ctk.CTkLabel(
            right_col,
            text="LOG",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=MUTED,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(10, 2))

        self.log_box = ctk.CTkTextbox(
            right_col,
            height=160,
            corner_radius=10,
            fg_color="#0c0e14",
            text_color="#a8b0c0",
            font=ctk.CTkFont(family="Consolas", size=11),
            activate_scrollbars=True,
        )
        self.log_box.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.log_box.configure(state="disabled")

    # ── helpers ───────────────────────────────────────────────────────────
    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{ts}] {msg}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def set_status(self, text: str, color: str = MUTED):
        self.status_lbl.configure(text=text, text_color=color)
        self.status_dot.configure(text_color=color)

    def _set_busy(self, busy: bool):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for b in (
            self.scan_btn,
            self.edit_btn,
            self.extract_btn,
            self.extract_all_btn,
        ):
            b.configure(state=state)

    def _open_path(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)  # noqa: S606

    def _open_wgs(self):
        p = wgs.package_path() / "SystemAppData" / "wgs"
        if p.is_dir():
            os.startfile(p)  # noqa: S606
        else:
            messagebox.showwarning("Not found", f"WGS folder missing:\n{p}")

    # ── scan ──────────────────────────────────────────────────────────────
    def scan(self):
        if self._busy:
            return
        self._set_busy(True)
        self.set_status("Scanning…", ORANGE)
        self.log("Scanning Microsoft Store Palworld saves…")

        def work():
            try:
                ok_plm, plm_msg = sav.palooz_available()
                found = worlds.discover_worlds()
                running = worlds.palworld_running()
                self.after(0, lambda: self._scan_done(found, ok_plm, plm_msg, running, None))
            except Exception as e:
                self.after(0, lambda: self._scan_done([], False, "", False, e))

        threading.Thread(target=work, daemon=True).start()

    def _scan_done(self, found, ok_plm, plm_msg, running, err):
        self._set_busy(False)
        if err:
            self.set_status("Scan failed", RED)
            self.log(f"ERROR: {err}")
            self.log(traceback.format_exc())
            return

        self.worlds = found
        self._rebuild_list()
        self.set_status(f"{len(found)} world(s)", GREEN if found else ORANGE)
        self.log(f"Found {len(found)} world(s).")
        self.log(f"PlM/Oodle: {plm_msg}")
        if running:
            self.log("⚠ Palworld is running — close it before applying edits.")
            self.set_status(f"{len(found)} world(s) · game open", ORANGE)
        if not wgs.is_palworld_installed():
            self.log("Palworld MS Store package not found.")

        if found:
            self.select_world(found[0])

    def _rebuild_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self.cards.clear()

        if not self.worlds:
            ctk.CTkLabel(
                self.list_frame,
                text="No worlds found.\nIs Palworld (MS Store) installed?",
                text_color=MUTED,
            ).pack(pady=40)
            return

        for info in self.worlds:
            card = WorldCard(self.list_frame, info, on_select=self.select_world)
            card.pack(fill="x", pady=4, padx=4)
            self.cards.append(card)

    def select_world(self, info: WorldInfo):
        self.selected = info
        for c in self.cards:
            c.set_selected(c.info.world_id == info.world_id and c.info.user_label == info.user_label)

        players = "\n".join(f"  · {p[:8]}…" for p in info.players) or "  · (none)"
        coop = info.coop_max if info.coop_max is not None else "?"
        server = info.server_max if info.server_max is not None else "?"
        text = (
            f"{info.short_id.upper()}…\n\n"
            f"Players: {info.player_count}\n{players}\n\n"
            f"CoopPlayerMaxNum:  {coop}\n"
            f"ServerPlayerMaxNum: {server}\n"
            f"Format: {info.worldoption_format or '—'}\n"
            f"Level: {_fmt_size(info.level_size)}\n"
            f"Total: {_fmt_size(info.total_size)}\n"
            f"Modified: {_fmt_time(info.mtime)}\n"
            f"Slot backups: {info.slot_backups}"
        )
        self.detail.configure(text=text, text_color=TEXT)
        self.edit_btn.configure(
            state="normal" if info.has_worldoption else "disabled"
        )
        self.log(f"Selected {info.short_id}… ({info.player_count} players)")

    # ── extract ───────────────────────────────────────────────────────────
    def extract_selected(self):
        if not self.selected:
            messagebox.showinfo("Extract", "Select a world first.")
            return
        if self._busy:
            return
        info = self.selected
        self._set_busy(True)
        self.set_status("Extracting…", ORANGE)

        def work():
            try:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = EXPORTS / f"{info.short_id}_{stamp}"
                out = worlds.extract_world(info, dest, include_slots=True)
                self.after(0, lambda: self._extract_done(out, None))
            except Exception as e:
                self.after(0, lambda: self._extract_done(None, e))

        threading.Thread(target=work, daemon=True).start()

    def _extract_done(self, out, err):
        self._set_busy(False)
        if err:
            self.set_status("Extract failed", RED)
            self.log(f"ERROR: {err}")
            messagebox.showerror("Extract failed", str(err))
            return
        self.set_status("Extracted", GREEN)
        self.log(f"Extracted → {out}")
        if messagebox.askyesno("Done", f"Extracted to:\n{out}\n\nOpen folder?"):
            self._open_path(out)

    def extract_all(self):
        if self._busy:
            return
        self._set_busy(True)
        self.set_status("Extracting all…", ORANGE)

        def work():
            try:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = EXPORTS / f"all_{stamp}"
                worlds.extract_all_files(wgs.PALWORLD_PACKAGE, dest)
                self.after(0, lambda: self._extract_done(dest, None))
            except Exception as e:
                self.after(0, lambda: self._extract_done(None, e))

        threading.Thread(target=work, daemon=True).start()

    # ── worldoption editor ────────────────────────────────────────────────
    def open_worldoption_editor(self):
        if not self.selected:
            messagebox.showinfo("Edit", "Select a world first.")
            return
        if not self.selected.has_worldoption:
            messagebox.showwarning(
                "No WorldOption",
                "This world has no WorldOption.sav.",
            )
            return
        self.log(f"Opening WorldOption editor for {self.selected.short_id}…")

        def on_saved():
            self.log("WorldOption saved to live store.")
            self.set_status("WorldOption saved", GREEN)
            # refresh cards/detail from updated WorldInfo fields
            if self.selected:
                self.select_world(self.selected)
                self._rebuild_list()
                for c in self.cards:
                    if (
                        c.info.world_id == self.selected.world_id
                        and c.info.user_label == self.selected.user_label
                    ):
                        self.select_world(c.info)
                        break

        WorldOptionEditor(
            self,
            self.selected,
            backup_dir=BACKUPS,
            on_saved=on_saved,
        )


def main():
    # high-DPI friendliness
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
