"""
Local filesystem client — reads CBZ/CBR/PDF directly from disk.
No download needed; covers are fast (direct file read).
Local file IDs: "local_{md5[:16]}" — persisted in data/local_registry.json
"""
import hashlib, json, os, sys, threading
from pathlib import Path
from storage import atomic_write

# Pasta dos dados (data/, cache/, credentials/). Padrão: raiz do projeto.
# OMNIVAULT_HOME permite guardar em outro lugar (e isola os testes).
_ROOT          = Path(os.getenv("OMNIVAULT_HOME") or Path(__file__).parent.parent)
REGISTRY_FILE  = _ROOT / "data/local_registry.json"
COMIC_EXTS     = {".cbz", ".cbr", ".pdf", ".zip", ".rar", ".cb7"}
_LOCK          = threading.RLock()

def _load_reg() -> dict:
    if not REGISTRY_FILE.exists():
        return {}
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return json.loads(REGISTRY_FILE.read_text(encoding=enc))
        except Exception:
            continue
    return {}

def _save_reg(reg: dict):
    with _LOCK:
        atomic_write(REGISTRY_FILE, json.dumps(reg, indent=2, ensure_ascii=False))

def path_to_id(path: str) -> str:
    lid = "local_" + hashlib.md5(path.encode()).hexdigest()[:16]
    with _LOCK:
        reg = _load_reg()
        if lid not in reg:
            reg[lid] = path
            _save_reg(reg)
    return lid

def id_to_path(lid: str) -> str | None:
    return _load_reg().get(lid)

def is_local(file_id: str) -> bool:
    return file_id.startswith("local_")

# ── Browser (folder picker) ───────────────────────────────────────────────────

def browse(path: str) -> dict:
    """Returns navigable directory listing for the folder picker UI."""
    if path == "__root__":
        if sys.platform == "win32":
            import string
            drives = [{"name": f"{d}:", "path": f"{d}:\\", "is_drive": True}
                      for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]
            return {"items": drives, "current": "__root__", "parent": None,
                    "current_name": "Este PC"}
        else:
            return {"items": [{"name": "/", "path": "/", "is_drive": True}],
                    "current": "__root__", "parent": None, "current_name": "Raiz"}

    p = Path(path)
    if not p.exists() or not p.is_dir():
        return {"error": "Caminho não encontrado", "items": [],
                "current": path, "parent": "__root__"}

    items = []
    try:
        for item in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            try:
                if item.is_dir() and not item.name.startswith("."):
                    items.append({"name": item.name, "path": str(item)})
            except PermissionError:
                continue
    except PermissionError:
        return {"error": "Sem permissão", "items": [], "current": path,
                "parent": str(p.parent)}

    parent = str(p.parent)
    if Path(parent) == p:
        parent = "__root__"

    return {"items": items, "current": path,
            "current_name": p.name or path, "parent": parent}

# ── Items listing ─────────────────────────────────────────────────────────────

def list_items(folder_path: str) -> dict:
    """List subfolders and comic files in a local directory."""
    p = Path(folder_path)
    if not p.exists():
        return {"folders": [], "comics": []}

    folders, comics = [], []
    try:
        for item in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            try:
                if item.is_dir() and not item.name.startswith("."):
                    try:
                        mtime = item.stat().st_mtime
                    except Exception:
                        mtime = 0
                    folders.append({"id": str(item), "name": item.name,
                                    "_local_folder_path": str(item), "modified": mtime})
                elif item.is_file() and item.suffix.lower() in COMIC_EXTS:
                    fid = path_to_id(str(item))
                    st = item.stat()
                    comics.append({"id": fid, "name": item.name,
                                   "size": st.st_size, "modified": st.st_mtime})
            except PermissionError:
                continue
    except PermissionError:
        pass

    return {"folders": folders, "comics": comics}

# ── File access ───────────────────────────────────────────────────────────────

def get_file_data(lid: str) -> bytes:
    path = id_to_path(lid)
    if not path:
        raise FileNotFoundError(f"Local ID não registado: {lid}")
    return Path(path).read_bytes()

def get_file_info(lid: str) -> dict:
    path = id_to_path(lid)
    if not path:
        raise FileNotFoundError(f"Local ID não registado: {lid}")
    p = Path(path)
    return {"id": lid, "name": p.name, "size": p.stat().st_size,
            "mimeType": "application/octet-stream"}


def peek_folder_cover(folder_path: str, depth: int = 4) -> str | None:
    """
    Encontra o primeiro ficheiro de HQ numa pasta local (recursivo).
    Retorna o PATH completo do ficheiro (não o local_id) para evitar
    problemas de registo/encoding.
    """
    if depth < 0:
        return None
    p = Path(folder_path)
    if not p.exists() or not p.is_dir():
        return None
    try:
        items = sorted(p.iterdir(), key=lambda x: x.name.lower())
        # Primeiro verifica ficheiros directos
        for item in items:
            try:
                if item.is_file() and item.suffix.lower() in COMIC_EXTS:
                    return str(item)  # Retorna path, não ID
            except Exception:
                continue
        # Depois desce para subpastas
        for item in items:
            try:
                if item.is_dir() and not item.name.startswith('.'):
                    result = peek_folder_cover(str(item), depth - 1)
                    if result:
                        return result
            except Exception:
                continue
    except PermissionError:
        pass
    return None
