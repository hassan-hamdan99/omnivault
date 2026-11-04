"""
Server-side reading state — syncs between PC and iPhone.
Um estado POR PERFIL: data/profiles/<pid>/reading_state.json (ver profiles.py).
Toda função recebe o id do perfil (pid) como primeiro argumento.
"""
import json, time, threading, functools
from storage import atomic_write
import profiles

# Lock reentrante: serializa load+modify+save das operações que escrevem,
# evitando corrupção E perda de atualizações concorrentes.
_LOCK = threading.RLock()

def _locked(fn):
    @functools.wraps(fn)
    def w(*a, **k):
        with _LOCK:
            return fn(*a, **k)
    return w

def _load(pid: str) -> dict:
    state_file = profiles.state_file(pid)
    if not state_file.exists():
        return {"in_progress": {}, "read": {}, "queue": []}
    # Try multiple encodings — Windows may have written cp1252 in a previous session
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            data = json.loads(state_file.read_text(encoding=enc))
            # Auto-heal: re-save as clean UTF-8 if we had to use a fallback
            if enc != "utf-8":
                print(f"[state] reading_state.json estava em {enc}, re-guardando como UTF-8")
                _save(pid, data)
            return data
        except Exception:
            continue
    # All encodings failed — return empty state (don't lose existing keys)
    print("[state] reading_state.json ilegível, a começar estado limpo")
    return {"in_progress": {}, "read": {}, "queue": []}

def _save(pid: str, state: dict):
    with _LOCK:
        atomic_write(profiles.state_file(pid), json.dumps(state, indent=2, ensure_ascii=False))

def get_state(pid: str) -> dict:
    return _load(pid)

@_locked
def replace_state(pid: str, data: dict) -> dict:
    """Importa/substitui o estado completo (backup). Mantém só as chaves válidas."""
    clean = {
        "in_progress": data.get("in_progress", {}) if isinstance(data.get("in_progress"), dict) else {},
        "read":        data.get("read", {})        if isinstance(data.get("read"), dict) else {},
        "queue":       data.get("queue", [])       if isinstance(data.get("queue"), list) else [],
        "lists":       data.get("lists", {})       if isinstance(data.get("lists"), dict) else {},
        "ratings":     data.get("ratings", {})     if isinstance(data.get("ratings"), dict) else {},
        "daily":       data.get("daily", {})       if isinstance(data.get("daily"), dict) else {},
    }
    _save(pid, clean)
    return clean

def get_saved_page(pid: str, file_id: str) -> int:
    """Página atual guardada no servidor (0 se não houver progresso)."""
    state = _load(pid)
    prog = state.get("in_progress", {}).get(file_id)
    return int(prog.get("page", 0)) if prog else 0

@_locked
def update_progress(pid: str, file_id: str, name: str, page: int, pages: int):
    state = _load(pid)
    if file_id in state["read"]:
        return  # already finished
    # Rastro diário para o heatmap: quantas páginas avançou em cada dia
    # (delta vs. última posição conhecida; retroceder/reler não conta).
    old = state["in_progress"].get(file_id) or {}
    delta = max(0, int(page) - int(old.get("page", 0)))
    if delta:
        day = time.strftime("%Y-%m-%d")
        daily = state.setdefault("daily", {})
        daily[day] = int(daily.get(day, 0)) + delta
    state["in_progress"][file_id] = {
        "name": name, "page": page, "pages": pages, "ts": int(time.time())
    }
    _save(pid, state)

@_locked
def finish(pid: str, file_id: str, name: str):
    state = _load(pid)
    state["in_progress"].pop(file_id, None)
    state["read"][file_id] = {"name": name, "ts": int(time.time())}
    # Remove from queue if present
    state["queue"] = [q for q in state["queue"] if q["id"] != file_id]
    _save(pid, state)

@_locked
def remove_progress(pid: str, file_id: str):
    state = _load(pid)
    state["in_progress"].pop(file_id, None)
    _save(pid, state)

@_locked
def remove_read(pid: str, file_id: str):
    state = _load(pid)
    state["read"].pop(file_id, None)
    _save(pid, state)

@_locked
def add_to_queue(pid: str, file_id: str, name: str):
    state = _load(pid)
    if not any(q["id"] == file_id for q in state["queue"]):
        state["queue"].append({"id": file_id, "name": name, "ts": int(time.time())})
        _save(pid, state)

@_locked
def remove_from_queue(pid: str, file_id: str):
    state = _load(pid)
    state["queue"] = [q for q in state["queue"] if q["id"] != file_id]
    _save(pid, state)

# ── Notas (1–5 estrelas por HQ; média por pasta é calculada no cliente) ──────

@_locked
def set_rating(pid: str, file_id: str, name: str, stars: int, parent: str | None = None):
    """stars 1–5 grava/atualiza; 0 remove. `parent` (id da pasta) permite a média
    por pasta — quando não vem (ex.: avaliado fora da biblioteca), preserva o antigo."""
    state = _load(pid)
    ratings = state.setdefault("ratings", {})
    if not stars:
        ratings.pop(file_id, None)
    else:
        old = ratings.get(file_id, {})
        ratings[file_id] = {
            "name": name, "stars": int(stars), "ts": int(time.time()),
            "parent": parent if parent is not None else old.get("parent"),
        }
    _save(pid, state)


# ── Listas personalizadas ─────────────────────────────────────────────────────

def get_lists(pid: str) -> dict:
    return _load(pid).get("lists", {})

@_locked
def create_list(pid: str, name: str) -> dict:
    import uuid
    state = _load(pid)
    if "lists" not in state:
        state["lists"] = {}
    lid = uuid.uuid4().hex[:8]
    state["lists"][lid] = {"name": name, "created": int(time.time()), "comics": []}
    _save(pid, state)
    return {"id": lid, **state["lists"][lid]}

@_locked
def rename_list(pid: str, list_id: str, name: str):
    state = _load(pid)
    if list_id in state.get("lists", {}):
        state["lists"][list_id]["name"] = name
        _save(pid, state)

@_locked
def delete_list(pid: str, list_id: str):
    state = _load(pid)
    state.get("lists", {}).pop(list_id, None)
    _save(pid, state)

@_locked
def add_to_list(pid: str, list_id: str, file_id: str, name: str, is_folder: bool = False):
    state = _load(pid)
    lst = state.get("lists", {}).get(list_id)
    if lst is None:
        return
    if not any(c["id"] == file_id for c in lst["comics"]):
        entry = {"id": file_id, "name": name, "added": int(time.time())}
        if is_folder:
            entry["is_folder"] = True
        lst["comics"].append(entry)
        _save(pid, state)

@_locked
def remove_from_list(pid: str, list_id: str, file_id: str):
    state = _load(pid)
    lst = state.get("lists", {}).get(list_id)
    if lst:
        lst["comics"] = [c for c in lst["comics"] if c["id"] != file_id]
        _save(pid, state)

# ── Estatísticas ──────────────────────────────────────────────────────────────

def get_stats(pid: str) -> dict:
    state = _load(pid)
    now = int(time.time())
    week_ago  = now - 7  * 86400
    month_ago = now - 30 * 86400

    read        = state.get("read", {})
    in_progress = state.get("in_progress", {})
    queue       = state.get("queue", [])
    lists       = state.get("lists", {})

    read_week  = sum(1 for v in read.values() if v.get("ts", 0) >= week_ago)
    read_month = sum(1 for v in read.values() if v.get("ts", 0) >= month_ago)
    pages_tracked = sum(v.get("page", 0) for v in in_progress.values())

    # Recentes (últimas 5 lidas)
    recent = sorted(
        [{"id": k, **v} for k, v in read.items()],
        key=lambda x: x.get("ts", 0), reverse=True
    )[:5]

    return {
        "total_read":       len(read),
        "total_in_progress": len(in_progress),
        "total_queue":      len(queue),
        "total_lists":      len(lists),
        "pages_tracked":    pages_tracked,
        "read_this_week":   read_week,
        "read_this_month":  read_month,
        "recent":           recent,
    }
