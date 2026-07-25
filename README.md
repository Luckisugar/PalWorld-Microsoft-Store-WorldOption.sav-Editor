# Palworld Microsoft Store — WorldOption.sav Editor

<p align="center">
  <img src="screenshots/01-main-window.png" alt="Main window — world list with real names" width="900" />
</p>

<p align="center">
  <img src="screenshots/02-worldoption-editor.png" alt="WorldOption.sav editor with search" width="900" />
</p>

Dark GUI toolkit to **scan**, **extract**, and **edit** Palworld world settings for the **Microsoft Store / PC Game Pass** version.

MS Store saves live in Xbox **WGS** containers (opaque folders under `%LocalAppData%\Packages\…`), not the Steam-style path. This tool:

1. Finds your worlds automatically  
2. Opens `WorldOption.sav` (PlZ zlib **or** PlM Oodle)  
3. Lets you edit all settings (including **CoopPlayerMaxNum**)  
4. Writes back into the live WGS blob with an auto-backup  

No manual file hunting required.

---

## Features

| Feature | Description |
|--------|-------------|
| **Scan worlds** | Lists MS Store worlds with player count, size, last modified, co-op max |
| **Edit WorldOption.sav** | Full settings editor with **search** |
| **Extract world** | Unpacks a world to normal folders (Steam-like layout) |
| **Extract all** | Full account dump |
| **Auto-backup** | Copies the original blob before every save |
| **PlZ + PlM** | Supports older zlib and newer Oodle saves |

---

## Requirements

- **Windows** (MS Store / Game Pass PC Palworld)
- **Python 3.10+** with **tkinter** (normal python.org install — *not* the embeddable-only build)
- For **PlM (Oodle)** worlds (most recent saves):
  - **Python 3.12** x64, and  
  - `vendor/palooz.pyd` (included in this repo)

The app runs on your main Python. PlM compress/decompress is handled by a **Python 3.12 worker** when needed.

### Recommended layout

```
Downloads\
  PalworldMSTool\          ← this repo
    run.bat
    app.py
    vendor\palooz.pyd
  python312\               ← optional but needed for PlM
    python.exe
    palooz.pyd             ← copy of vendor\palooz.pyd
```

If `..\python312\python.exe` is missing, place a Python **3.12** install there (or edit paths in `palworld_ms/sav.py`).

---

## Quick start

```bat
git clone https://github.com/Luckisugar/PalWorld-Microsoft-Store-WorldOption.sav-Editor.git
cd PalWorld-Microsoft-Store-WorldOption.sav-Editor
run.bat
```

Or:

```bat
python -m pip install -r requirements.txt
python app.py
```

1. **Close Palworld** completely.  
2. Click **Scan saves**.  
3. Select your world.  
4. Click **Edit WorldOption.sav**.  
5. Search for `CoopPlayerMaxNum` (or any other setting).  
6. Change values → **Save to live save**.  
7. Launch the game and load that world.

---

## Notes & limits

- Close the game before saving, or in-memory autosave can overwrite your edit.  
- UI may still show `x/4` even when more players can join.  
- Raising co-op max in the file does **not** always bypass every Xbox/session invite limit — dedicated servers are more reliable for large groups.  
- This is an unofficial community tool. Use at your own risk; always keep backups (the tool creates them under `backups/`).

---

## Project layout

```
app.py                 Main window
editor_window.py       WorldOption editor + search
run.bat                Launcher (installs deps if needed)
requirements.txt
palworld_ms/
  wgs.py               WGS container reader
  sav.py               PlZ/PlM sav helpers
  sav_worker.py        Python 3.12 Oodle worker CLI
  worlds.py            Discover / extract / backup
  worldoption.py       Full WorldOption load/edit/save
vendor/
  palooz.pyd           Oodle bindings (Windows x64, CPython 3.12)
```

---

## Credits

- WGS container layout: [Z1ni/XGP-save-extractor](https://github.com/Z1ni/XGP-save-extractor)  
- GVAS parse/write: [cheahjs/palworld-save-tools](https://github.com/cheahjs/palworld-save-tools)  
- Oodle (`palooz`): PalworldSaveTools / ooz ecosystem  

---

## License

Use freely for personal / community tooling. Third-party binaries (e.g. `palooz`) keep their own licenses.
