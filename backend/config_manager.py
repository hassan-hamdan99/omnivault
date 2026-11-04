"""
Manages config.json — folder sources (Drive + Local), ordering, naming.
Migrates from .env on first run.

IMPORTANT: always use explicit encoding="utf-8" on all file I/O.
Windows default encoding (cp1252) breaks JSON with accented characters.
"""
import json, os, uuid, threading, functools
from pathlib import Path
from storage import atomic_write

_ROOT       = Path(__file__).parent.parent
CONFIG_FILE = _ROOT / "data/config.json"

_LOCK = threading.RLock()

def _locked(fn):
    @functools.wraps(fn)
    def w(*a, **k):
        with _LOCK:
            return fn(*a, **k)
    return w


def _load() -> dict:
    if not CONFIG_FILE.exists():
        return _migrate_from_env()

    # Try multiple encodings — Windows may have written cp1252
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            content = CONFIG_FILE.read_text(encoding=enc)
            data = json.loads(content)
            # Auto-heal: re-save as clean UTF-8 if we had to use a fallback
            if enc != "utf-8":
                print(f"[config] config.json estava em {enc}, re-guardando como UTF-8")
                _save(data)
            return data
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue

    # All encodings failed — backup and re-migrate
    backup = CONFIG_FILE.with_suffix(".json.bak")
    try:
        CONFIG_FILE.rename(backup)
        print(f"[config] config.json ilegível, backup guardado em {backup}")
    except Exception:
        pass
    return _migrate_from_env()


def _save(cfg: dict):
    with _LOCK:
        atomic_write(CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False))


def _migrate_from_env() -> dict:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    raw = os.getenv("DRIVE_FOLDERS", "")
    folders = []
    for i, entry in enumerate(raw.split(",")):
        entry = entry.strip()
        if ":" not in entry:
            continue
        name, fid = entry.split(":", 1)
        folders.append({
            "id": uuid.uuid4().hex[:8],
            "name": name.strip(),
            "type": "drive",
            "drive_id": fid.strip(),
            "order": i,
        })
    cfg = {"folders": folders}
    _save(cfg)
    return cfg


def get_folders() -> list[dict]:
    return sorted(_load()["folders"], key=lambda f: f.get("order", 0))


@_locked
def add_drive_folder(name: str, drive_id: str) -> dict:
    cfg = _load()
    folder = {"id": uuid.uuid4().hex[:8], "name": name,
              "type": "drive", "drive_id": drive_id, "order": len(cfg["folders"])}
    cfg["folders"].append(folder)
    _save(cfg)
    return folder


@_locked
def add_local_folder(name: str, path: str) -> dict:
    cfg = _load()
    folder = {"id": uuid.uuid4().hex[:8], "name": name,
              "type": "local", "local_path": path, "order": len(cfg["folders"])}
    cfg["folders"].append(folder)
    _save(cfg)
    return folder


@_locked
def rename_folder(folder_id: str, name: str):
    cfg = _load()
    for f in cfg["folders"]:
        if f["id"] == folder_id:
            f["name"] = name
            break
    _save(cfg)


@_locked
def remove_folder(folder_id: str):
    cfg = _load()
    cfg["folders"] = [f for f in cfg["folders"] if f["id"] != folder_id]
    _save(cfg)


@_locked
def reorder_folders(ordered_ids: list[str]):
    cfg = _load()
    pos = {fid: i for i, fid in enumerate(ordered_ids)}
    for f in cfg["folders"]:
        if f["id"] in pos:
            f["order"] = pos[f["id"]]
    _save(cfg)
