"""
Perfis (estilo Netflix) — cada perfil tem nome, avatar e o SEU estado de leitura
(andamento, lidas, fila, notas, listas, heatmap). A biblioteca (pastas, capas,
Drive, cache) é compartilhada entre todos.

  data/profiles.json                      → {"profiles": [{id, name, avatar, photo_v, created}]}
  data/profiles/<id>/reading_state.json   → estado de leitura do perfil
  data/profiles/<id>/avatar.jpg           → foto enviada (opcional; senão usa o avatar pronto)

Migração (1ª execução): o data/reading_state.json antigo (de antes dos perfis)
vira o estado do perfil inicial e o original fica guardado como
reading_state.pre-perfis.json.
"""
import json, re, shutil, threading, time, uuid, functools
from pathlib import Path
from storage import atomic_write

_ROOT         = Path(__file__).parent.parent
PROFILES_FILE = _ROOT / "data/profiles.json"
PROFILES_DIR  = _ROOT / "data/profiles"
LEGACY_STATE  = _ROOT / "data/reading_state.json"
LEGACY_BACKUP = _ROOT / "data/reading_state.pre-perfis.json"

_ID_RE = re.compile(r"^[a-z0-9]{1,32}$")
_LOCK  = threading.RLock()

# Perfil inicial (só numa instalação nova, quando data/profiles.json ainda não
# existe). Herda o estado de leitura antigo, se houver. Renomeie e crie outros
# perfis pela tela "Quem está lendo?" → Gerenciar perfis.
_SEED = [
    {"id": "principal", "name": "Leitor", "avatar": "p1"},
]

def _locked(fn):
    @functools.wraps(fn)
    def w(*a, **k):
        with _LOCK:
            return fn(*a, **k)
    return w

def _load() -> dict:
    if not PROFILES_FILE.exists():
        return {"profiles": []}
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            data = json.loads(PROFILES_FILE.read_text(encoding=enc))
            if enc != "utf-8":
                print(f"[profiles] profiles.json estava em {enc}, re-guardando como UTF-8")
                _save(data)
            return data
        except Exception:
            continue
    print("[profiles] profiles.json ilegível")
    return {"profiles": []}

def _save(data: dict):
    with _LOCK:
        atomic_write(PROFILES_FILE, json.dumps(data, indent=2, ensure_ascii=False))

def _dir(pid: str) -> Path:
    return PROFILES_DIR / pid

def state_file(pid: str) -> Path:
    return _dir(pid) / "reading_state.json"

def photo_file(pid: str) -> Path:
    return _dir(pid) / "avatar.jpg"

@_locked
def ensure():
    """Cria os perfis iniciais e migra o estado antigo. Idempotente: pode ser
    interrompida a meio e rodar de novo sem perder nada."""
    if PROFILES_FILE.exists():
        return
    first = _SEED[0]["id"]
    target = state_file(first)
    target.parent.mkdir(parents=True, exist_ok=True)
    if LEGACY_STATE.exists():
        if not target.exists():
            shutil.copy2(LEGACY_STATE, target)
        LEGACY_STATE.replace(LEGACY_BACKUP)
        print(f"[profiles] estado de leitura migrado para o perfil '{_SEED[0]['name']}'")
    now = int(time.time())
    _save({"profiles": [{**p, "photo_v": 0, "created": now} for p in _SEED]})

def list_profiles() -> list[dict]:
    return _load().get("profiles", [])

def exists(pid: str | None) -> bool:
    return bool(pid) and bool(_ID_RE.match(pid)) and any(p["id"] == pid for p in list_profiles())

def _clean_name(name: str) -> str:
    name = " ".join(str(name or "").split())[:40]
    if not name:
        raise ValueError("Nome obrigatório")
    return name

@_locked
def create(name: str, avatar: str) -> dict:
    data = _load()
    p = {"id": uuid.uuid4().hex[:8], "name": _clean_name(name), "avatar": avatar or "p1",
         "photo_v": 0, "created": int(time.time())}
    data.setdefault("profiles", []).append(p)
    _dir(p["id"]).mkdir(parents=True, exist_ok=True)
    _save(data)
    return p

@_locked
def update(pid: str, name: str | None = None, avatar: str | None = None) -> dict | None:
    data = _load()
    for p in data.get("profiles", []):
        if p["id"] == pid:
            if name is not None:
                p["name"] = _clean_name(name)
            if avatar is not None:
                p["avatar"] = avatar
            _save(data)
            return p
    return None

@_locked
def delete(pid: str) -> bool:
    """Remove o perfil. Os dados não são apagados: a pasta vai para
    data/profiles/_excluidos/ (recuperável à mão)."""
    data = _load()
    profs = data.get("profiles", [])
    if len(profs) <= 1 or not any(p["id"] == pid for p in profs):
        return False
    data["profiles"] = [p for p in profs if p["id"] != pid]
    _save(data)
    src = _dir(pid)
    if src.exists():
        dst = PROFILES_DIR / "_excluidos" / f"{pid}-{int(time.time())}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    return True

@_locked
def set_photo(pid: str, jpeg: bytes | None) -> dict | None:
    """Grava (ou remove, com None) a foto do perfil. photo_v muda a cada troca —
    o front usa como ?v= para furar caches."""
    data = _load()
    for p in data.get("profiles", []):
        if p["id"] == pid:
            f = photo_file(pid)
            if jpeg is None:
                f.unlink(missing_ok=True)
                p["photo_v"] = 0
            else:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(jpeg)
                p["photo_v"] = int(time.time() * 1000)
            _save(data)
            return p
    return None
