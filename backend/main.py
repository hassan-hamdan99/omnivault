"""Omnivault — servidor local — http://localhost:8000"""
import os, shutil, threading
from pathlib import Path
import hashlib

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, UploadFile, Request, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from drive_client import DriveClient
import drive_client as drive_client_mod
from extractor import (extract_cover, extract_cover_partial, extract_page, get_page_count,
                       extract_cover_path, extract_page_path, get_page_count_path,
                       get_page_count_partial)
import json
from storage import atomic_write
import config_manager as cfg_mgr
import reading_manager as rdg
import profiles as prof
import local_client as lc

APP_VERSION = "1.1.0"
app = FastAPI(title="Omnivault", version=APP_VERSION)

# ── Mesma origem ──────────────────────────────────────────────────────────────
# O app (PC, iPad, PWA) carrega a página e chama a API no MESMO endereço, então não
# precisa de CORS. Sem CORS, um site qualquer aberto num navegador da rede não lê
# as respostas da API; e o filtro abaixo recusa chamadas vindas de outra origem
# (ex.: um site tentando POST /api/shutdown). CORS_ORIGINS libera origens extras.
_cors_origins = [o.strip().rstrip("/") for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_methods=["*"], allow_headers=["*"])
_ALLOW_ANY_ORIGIN = "*" in _cors_origins

@app.middleware("http")
async def _same_origin_only(request, call_next):
    origin = request.headers.get("origin")
    if origin and not _ALLOW_ANY_ORIGIN and request.url.path.startswith(("/api/", "/auth/")):
        from urllib.parse import urlsplit
        same = urlsplit(origin).netloc.lower() == (request.headers.get("host") or "").lower()
        if not same and origin.rstrip("/") not in _cors_origins:
            return Response("Origem não permitida", status_code=403)
    return await call_next(request)

# Limita extrações pesadas simultâneas (7-Zip/PyMuPDF) para não saturar a máquina.
_EXTRACT_SEM = threading.Semaphore(int(os.getenv("EXTRACT_WORKERS", "4")))

# Cache persistente de contagem de páginas (alimenta o tooltip de hover).
_PC_FILE = Path(os.getenv("OMNIVAULT_HOME") or Path(__file__).parent.parent) / "data/page_counts.json"
_pc_lock = threading.Lock()
try:
    _PAGE_COUNTS = json.loads(_PC_FILE.read_text(encoding="utf-8"))
except Exception:
    _PAGE_COUNTS = {}
def _pc_set(fid: str, n) -> None:
    if not n:
        return
    _PAGE_COUNTS[fid] = int(n)
    with _pc_lock:
        try:
            atomic_write(_PC_FILE, json.dumps(_PAGE_COUNTS))
        except Exception:
            pass

_ROOT       = Path(os.getenv("OMNIVAULT_HOME") or Path(__file__).parent.parent)
COVER_CACHE = _ROOT / "cache/covers"
MAIN_COVERS = _ROOT / "cache/main_covers"
# Capas definidas manualmente pelo utilizador: cópia durável fora de cache/,
# para sobreviverem a limpezas de cache e não dependerem do ficheiro original.
CUSTOM_COVERS = _ROOT / "data/custom_covers"
for d in [COVER_CACHE, MAIN_COVERS, CUSTOM_COVERS, _ROOT/"cache/comics", _ROOT/"data"]:
    d.mkdir(parents=True, exist_ok=True)

drive = DriveClient()
CACHE_1DAY  = "public, max-age=86400"
CACHE_1WEEK = "public, max-age=604800"

def _thumb(data: bytes | None) -> bytes | None:
    """Reduz uma capa ao tamanho da grade (máx. 300x450 JPEG).

    As páginas extraídas vinham em resolução completa (~900 KB, até 4 MB) e
    eram servidas assim na grade — ~20x mais bytes do que o necessário no
    Wi-Fi/iPhone. As PÁGINAS de leitura continuam em resolução completa;
    isto afeta só as capas."""
    if not data:
        return data
    try:
        import io as _io
        from PIL import Image
        img = Image.open(_io.BytesIO(data)).convert("RGB")
        img.thumbnail((300, 450), Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, "JPEG", quality=88, optimize=True)
        out = buf.getvalue()
        return out if len(out) < len(data) else data
    except Exception:
        return data

def _fr(path: Path, ttl=CACHE_1WEEK):
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": ttl})
def _br(data: bytes, ttl=CACHE_1WEEK):
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": ttl})

# ── LRU cache eviction ────────────────────────────────────────────────────────
def _evict():
    max_gb = float(os.getenv("CACHE_MAX_GB", "15"))
    d = _ROOT / "cache/comics"
    files = [f for f in d.iterdir() if f.is_file()]
    total = sum(f.stat().st_size for f in files) / 1024**3
    if total <= max_gb: return
    for f in sorted(files, key=lambda x: x.stat().st_atime):
        gb = f.stat().st_size / 1024**3; f.unlink()
        pd = COVER_CACHE / f"pages_{f.stem}"
        if pd.exists(): shutil.rmtree(pd)
        total -= gb
        if total <= max_gb * 0.85: break

# ── Page pregeneration ────────────────────────────────────────────────────────
_pregen_active: set[str] = set()

def _pregen(file_id: str, filename: str, start: int, count: int):
    if file_id in _pregen_active: return
    _pregen_active.add(file_id)
    try:
        pd = COVER_CACHE / f"pages_{file_id}"; pd.mkdir(exist_ok=True)
        missing = [p for p in range(start, start+count) if not (pd/f"{p}.jpg").exists()]
        if not missing: return
        is_loc = lc.is_local(file_id)
        path = lc.id_to_path(file_id) if is_loc else None
        data = None if is_loc else _get_data(file_id, filename)
        for p in missing:
            with _EXTRACT_SEM:
                pg = extract_page_path(path, p) if is_loc else extract_page(data, filename, p)
            if pg: (pd/f"{p}.jpg").write_bytes(pg)
    except Exception as e:
        print(f"[pregen] {e}")
    finally:
        _pregen_active.discard(file_id)

def _bg_pregen(file_id, filename, start, count):
    threading.Thread(target=_pregen, args=(file_id, filename, start, count), daemon=True).start()

# ── Unified data access (Drive + Local) ──────────────────────────────────────
def _is_local_folder_id(folder_id: str) -> bool:
    """Um id de pasta local é um caminho (Unix '/...' ou Windows 'C:\\...')."""
    return (folder_id.startswith("/") or
            (len(folder_id) >= 2 and folder_id[1] == ":") or
            (len(folder_id) >= 3 and folder_id[2] in ("/", "\\")))

def _get_data(file_id: str, filename: str) -> bytes:
    if lc.is_local(file_id):
        return lc.get_file_data(file_id)
    return drive.download_file(file_id, filename)

# Cache de metadados (nome/tamanho) para evitar chamadas repetidas à API do
# Drive a cada página virada. Locais são baratos (stat) e não entram no cache.
_INFO_CACHE: dict[str, dict] = {}

def _get_info(file_id: str) -> dict:
    if lc.is_local(file_id):
        return lc.get_file_info(file_id)
    cached = _INFO_CACHE.get(file_id)
    if cached is not None:
        return cached
    info = drive.get_file_info(file_id)
    _INFO_CACHE[file_id] = info
    return info

def _effective_name(info: dict) -> str:
    return info.get("name", "unknown.cbz")

def _get_cover(file_id: str, filename: str) -> bytes | None:
    if lc.is_local(file_id):
        p = lc.id_to_path(file_id)
        if not p:
            return None
        try:
            with _EXTRACT_SEM:
                return _thumb(extract_cover_path(p))
        except Exception as e:
            print(f"[cover] Erro local '{filename}': {e}")
            return None
    return _thumb(extract_cover_partial(file_id, filename, drive))

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.get("/auth/status")
def auth_status():
    return {"authenticated": drive.is_authenticated()}

def _credentials_problem(data) -> str | None:
    """None se `data` (JSON já lido) é uma credencial OAuth do tipo Desktop; senão, o motivo."""
    if not isinstance(data, dict):
        return "O arquivo não é uma credencial do Google."
    if "web" in data and "installed" not in data:
        return ("Essa credencial é do tipo \"Aplicativo da Web\". Crie um ID do cliente OAuth do tipo "
                "\"App para computador (Desktop)\" e envie o JSON dele (passo 6 do guia).")
    inst = data.get("installed")
    if not isinstance(inst, dict) or not inst.get("client_id") or not inst.get("client_secret"):
        return ("O arquivo não parece o JSON baixado do Google Cloud (falta \"installed\", "
                "\"client_id\" ou \"client_secret\").")
    return None

def _onboarding(error: str | None = None, status: int = 200) -> HTMLResponse:
    import html as _html
    err = f'<div class="err">{_html.escape(error)}</div>' if error else ""
    return HTMLResponse(_ONBOARDING_HTML.replace("{{ERR}}", err), status_code=status)

def _is_local_client(request: Request) -> bool:
    host = (request.client.host if request.client else "") or ""
    return host in ("127.0.0.1", "::1", "localhost") or host.startswith("::ffff:127.")

@app.get("/auth/login")
def auth_login():
    if drive_client_mod.CREDENTIALS_FILE.exists():
        try:
            problem = _credentials_problem(json.loads(
                drive_client_mod.CREDENTIALS_FILE.read_text(encoding="utf-8-sig")))
        except Exception:
            problem = "O credentials.json atual não é um JSON válido."
        if problem:
            return _onboarding("Problema no credentials.json atual: " + problem)
    try:
        return RedirectResponse(drive.get_auth_url())
    except FileNotFoundError:
        return _onboarding()

@app.post("/auth/credentials")
async def auth_credentials_upload(request: Request, file: UploadFile):
    """Recebe o JSON do cliente OAuth pela página de configuração e salva em
    credentials/credentials.json. Só no próprio PC (o login também só completa lá)."""
    if not _is_local_client(request):
        return _onboarding("Envie o arquivo pelo navegador do PC onde o Omnivault roda "
                           "(http://localhost:8000).", 403)
    raw = await file.read(64 * 1024 + 1)
    if len(raw) > 64 * 1024:
        return _onboarding("Arquivo grande demais para ser uma credencial do Google.", 400)
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        return _onboarding("O arquivo escolhido não é um JSON válido.", 400)
    problem = _credentials_problem(data)
    if problem:
        return _onboarding(problem, 400)
    atomic_write(drive_client_mod.CREDENTIALS_FILE, json.dumps(data, indent=2))
    print("[auth] credentials.json salvo pela página de configuração")
    return RedirectResponse("/auth/login", status_code=303)

_ONBOARDING_HTML = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Configurar Google Drive — Omnivault</title>
<style>
 body{margin:0;background:#0F1115;color:#F5F7FA;font-family:system-ui,sans-serif;
   display:flex;min-height:100vh;align-items:center;justify-content:center;padding:2rem}
 .card{background:#1F2530;border:1px solid #303A49;border-radius:16px;
   max-width:560px;padding:2rem 2.2rem;line-height:1.6}
 h1{font-size:1.3rem;margin:0 0 .3rem;color:#E3643B}
 p{color:#B3BCC9;font-size:.92rem}
 ol{color:#B3BCC9;font-size:.9rem;padding-left:1.2rem}
 code{background:#0F1115;border:1px solid #303A49;border-radius:5px;
   padding:.1rem .4rem;color:#D9A44A;font-size:.85em}
 a{color:#E3643B} .b{margin-top:1.4rem}
 .btn{display:inline-block;background:#E3643B;color:#0F1115;text-decoration:none;border:0;
   font:inherit;font-weight:700;padding:.6rem 1.2rem;border-radius:8px;cursor:pointer}
 .btn2{background:transparent;color:#B3BCC9;border:1px solid #303A49}
 .up{background:#0F1115;border:1px dashed #303A49;border-radius:12px;padding:1rem 1.1rem;margin:1rem 0}
 .up p{margin:.2rem 0 .7rem} input[type=file]{color:#B3BCC9;font:inherit;font-size:.85rem;max-width:100%}
 .err{background:#3a1d18;border:1px solid #E3643B;color:#F5D0C5;border-radius:10px;
   padding:.7rem .9rem;font-size:.88rem;margin:.8rem 0}
</style></head><body><div class="card">
 <h1>Conectar o Google Drive</h1>
 <p>O acesso ao Google Drive precisa de uma credencial OAuth sua (gratuita, feita uma vez só).
 Só é necessário para fontes do Drive: pastas <strong>locais</strong> já funcionam sem isso.</p>
 {{ERR}}
 <ol>
  <li>Abra o <a href="https://console.cloud.google.com" target="_blank" rel="noopener">Google Cloud Console</a> e crie um projeto.</li>
  <li>Ative a <strong>Google Drive API</strong>.</li>
  <li>Configure a <strong>tela de consentimento</strong> (tipo Externo) e <strong>publique o app</strong>
   (ou adicione seu e-mail em <em>Usuários de teste</em>).</li>
  <li><em>Credenciais → Criar credenciais → ID do cliente OAuth</em>, tipo <strong>App para computador (Desktop)</strong>.</li>
  <li>Clique em <strong>Fazer download do JSON</strong> e envie o arquivo aqui embaixo (não precisa renomear).</li>
 </ol>
 <form class="up" method="post" action="/auth/credentials" enctype="multipart/form-data">
  <p><strong>Enviar a credencial</strong> (o arquivo <code>client_secret_….json</code> baixado):</p>
  <input type="file" name="file" accept=".json,application/json" required>
  <div class="b" style="margin-top:.9rem"><button class="btn" type="submit">Enviar e conectar →</button></div>
 </form>
 <p>Passo a passo com todos os cliques: <a href="https://github.com/hassan-hamdan99/omnivault/blob/main/docs/GOOGLE_DRIVE.md" target="_blank" rel="noopener">guia do Google Drive</a>
 (também em <code>docs/GOOGLE_DRIVE.md</code>).</p>
 <div class="b"><a class="btn btn2" href="/">← Voltar ao Omnivault</a></div>
</div></body></html>"""

@app.get("/auth/callback")
def auth_callback(code: str, state: str):
    try: drive.exchange_code(code, state)
    except ValueError as e: raise HTTPException(400, str(e))
    return RedirectResponse("/")

@app.post("/auth/logout")
def auth_logout():
    """Remove o token OAuth e desliga o Google Drive."""
    drive.logout()
    return {"ok": True}

@app.get("/api/netinfo")
def netinfo():
    """IP local + porta — mostrado na Home para abrir no celular (mesmo Wi-Fi)."""
    import socket
    ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))   # não envia nada; só descobre a interface de saída
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    return {"ip": ip, "port": int(os.getenv("PORT", "8000"))}

@app.post("/api/shutdown")
def api_shutdown():
    """Encerra o servidor Omnivault de forma limpa."""
    import os, signal, threading
    threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    return {"ok": True, "message": "Omnivault a encerrar..."}

# ── Config: folders ───────────────────────────────────────────────────────────
@app.get("/api/config/folders")
def list_folders():
    return cfg_mgr.get_folders()

class DriveAdd(BaseModel):
    name: str
    link: str  # full Drive URL or just the ID

class LocalAdd(BaseModel):
    name: str
    path: str

class RenameBody(BaseModel):
    name: str

class ReorderBody(BaseModel):
    ids: list[str]

@app.post("/api/config/folders/drive")
def add_drive(body: DriveAdd):
    # Extract ID from full URL if needed
    link = body.link.strip()
    if "drive.google.com" in link:
        import re
        m = re.search(r"folders/([a-zA-Z0-9_-]+)", link)
        if not m: raise HTTPException(400, "Link inválido")
        drive_id = m.group(1)
    else:
        drive_id = link
    return cfg_mgr.add_drive_folder(body.name, drive_id)

@app.post("/api/config/folders/local")
def add_local(body: LocalAdd):
    if not Path(body.path).exists():
        raise HTTPException(400, f"Caminho não encontrado: {body.path}")
    return cfg_mgr.add_local_folder(body.name, body.path)

@app.put("/api/config/folders/{folder_id}")
def rename_folder(folder_id: str, body: RenameBody):
    cfg_mgr.rename_folder(folder_id, body.name)
    return {"ok": True}

@app.delete("/api/config/folders/{folder_id}")
def delete_folder(folder_id: str):
    cfg_mgr.remove_folder(folder_id)
    return {"ok": True}

@app.post("/api/config/folders/reorder")
def reorder(body: ReorderBody):
    cfg_mgr.reorder_folders(body.ids)
    return {"ok": True}

# ── Local browser ─────────────────────────────────────────────────────────────
@app.get("/api/local/browse")
def local_browse(path: str = "__root__"):
    return lc.browse(path)

@app.get("/api/local/items")
def local_items(path: str):
    return lc.list_items(path)

# ── Library items (Drive) ────────────────────────────────────────────────────
@app.get("/api/items")
def list_items(folder_id: str):
    if not drive.is_authenticated():
        raise HTTPException(401)
    return drive.list_items(folder_id)

@app.get("/api/search")
def search(q: str = Query(..., min_length=2)):
    if not drive.is_authenticated(): raise HTTPException(401)
    return {"results": drive.search_comics(q)}

# ── Perfis ────────────────────────────────────────────────────────────────────
# O perfil ativo vem no header X-Profile (o front injeta em toda chamada /api/;
# ver o wrapper de fetch em index.html/reader.html). Estado de leitura, listas
# e stats são por perfil; a biblioteca é compartilhada.
prof.ensure()

def _profile(x_profile: str | None = Header(None)) -> str:
    """Dependência dos endpoints por perfil. 409 = o front precisa escolher perfil."""
    if not prof.exists(x_profile):
        raise HTTPException(409, "Selecione um perfil")
    return x_profile

def _profile_opt(x_profile: str | None = Header(None)) -> str | None:
    return x_profile if prof.exists(x_profile) else None

class ProfileBody(BaseModel):
    name: str | None = None
    avatar: str | None = None

@app.get("/api/profiles")
def profiles_list():
    return prof.list_profiles()

@app.post("/api/profiles")
def profiles_create(b: ProfileBody):
    try:
        return prof.create(b.name or "", b.avatar or "p1")
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.put("/api/profiles/{pid}")
def profiles_update(pid: str, b: ProfileBody):
    try:
        p = prof.update(pid, b.name, b.avatar)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not p: raise HTTPException(404)
    return p

@app.delete("/api/profiles/{pid}")
def profiles_delete(pid: str):
    if not prof.delete(pid):
        raise HTTPException(400, "Não foi possível excluir (o último perfil não pode ser excluído)")
    return {"ok": True}

@app.get("/api/profiles/{pid}/photo")
def profiles_photo(pid: str, request: Request):
    if not prof.exists(pid): raise HTTPException(404)
    f = prof.photo_file(pid)
    if not f.exists(): raise HTTPException(404)
    return _cover_resp(request, f)   # mutável → no-cache + ETag

@app.post("/api/profiles/{pid}/photo")
async def profiles_photo_upload(pid: str, file: UploadFile):
    """Foto do perfil: recorte quadrado central, 256x256 JPEG."""
    from PIL import Image, ImageOps
    import io as _io
    if not prof.exists(pid): raise HTTPException(404)
    try:
        img = Image.open(_io.BytesIO(await file.read()))
        img = ImageOps.exif_transpose(img).convert("RGB")   # fotos de celular vêm rotacionadas via EXIF
        img = ImageOps.fit(img, (256, 256), Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, "JPEG", quality=88, optimize=True)
    except Exception as e:
        raise HTTPException(400, f"Imagem inválida: {e}")
    return prof.set_photo(pid, buf.getvalue())

@app.delete("/api/profiles/{pid}/photo")
def profiles_photo_delete(pid: str):
    p = prof.set_photo(pid, None)
    if not p: raise HTTPException(404)
    return p

# ── Reading state ─────────────────────────────────────────────────────────────
@app.get("/api/reading/state")
def reading_state(pid: str = Depends(_profile)):
    return rdg.get_state(pid)

class ProgressBody(BaseModel):
    file_id: str; name: str; page: int; pages: int

class FinishBody(BaseModel):
    file_id: str; name: str

class QueueBody(BaseModel):
    file_id: str; name: str

@app.post("/api/reading/progress")
def save_progress(b: ProgressBody, pid: str = Depends(_profile)):
    rdg.update_progress(pid, b.file_id, b.name, b.page, b.pages); return {"ok": True}

@app.post("/api/reading/finish")
def finish_comic(b: FinishBody, pid: str = Depends(_profile)):
    rdg.finish(pid, b.file_id, b.name); return {"ok": True}

@app.delete("/api/reading/progress/{file_id}")
def del_progress(file_id: str, pid: str = Depends(_profile)):
    rdg.remove_progress(pid, file_id); return {"ok": True}

@app.delete("/api/reading/read/{file_id}")
def del_read(file_id: str, pid: str = Depends(_profile)):
    rdg.remove_read(pid, file_id); return {"ok": True}

@app.post("/api/reading/queue")
def add_queue(b: QueueBody, pid: str = Depends(_profile)):
    rdg.add_to_queue(pid, b.file_id, b.name); return {"ok": True}

class RateBody(BaseModel):
    file_id: str; name: str; stars: int; parent: str | None = None

@app.post("/api/reading/rate")
def rate_comic(b: RateBody, pid: str = Depends(_profile)):
    """Nota 1–5 por HQ (0 remove). A média por pasta vem do campo parent."""
    if not 0 <= b.stars <= 5:
        raise HTTPException(400, "Nota deve ser de 0 a 5")
    rdg.set_rating(pid, b.file_id, b.name, b.stars, b.parent)
    return {"ok": True}

@app.delete("/api/reading/queue/{file_id}")
def del_queue(file_id: str, pid: str = Depends(_profile)):
    rdg.remove_from_queue(pid, file_id); return {"ok": True}

# ── Backup do estado de leitura ─────────────────────────────────────────────────
@app.post("/api/reading/import")
def reading_import(data: dict, pid: str = Depends(_profile)):
    """Importa um backup do estado de leitura (substitui o actual do perfil)."""
    return rdg.replace_state(pid, data)

# ── Marcar pasta inteira como lida ──────────────────────────────────────────────
def _collect_comics(folder_id: str, depth: int = 6) -> list[dict]:
    """Lista recursivamente todos os comics dentro de uma pasta (Drive ou local)."""
    out: list[dict] = []
    is_local = (folder_id.startswith("/") or
                (len(folder_id) >= 2 and folder_id[1] == ":"))
    def walk_local(path, d):
        if d < 0:
            return
        data = lc.list_items(path)
        out.extend({"id": c["id"], "name": c["name"]} for c in data["comics"])
        for f in data["folders"]:
            walk_local(f["_local_folder_path"], d - 1)
    def walk_drive(fid, d):
        if d < 0:
            return
        data = drive.list_items(fid)
        out.extend({"id": c["id"], "name": c["name"]} for c in data["comics"])
        for f in data["folders"]:
            walk_drive(f["id"], d - 1)
    try:
        if is_local:
            walk_local(folder_id, depth)
        else:
            if not drive.is_authenticated():
                raise HTTPException(401)
            walk_drive(folder_id, depth)
    except HTTPException:
        raise
    except Exception as e:
        print(f"[finish-folder] {e}")
    return out

@app.post("/api/reading/finish-folder")
def finish_folder(folder_id: str, pid: str = Depends(_profile)):
    comics = _collect_comics(folder_id)
    for c in comics:
        rdg.finish(pid, c["id"], c["name"])
    return {"ok": True, "count": len(comics)}

# ── Covers ────────────────────────────────────────────────────────────────────
def _cover_key(folder_id: str) -> str:
    """Nome do ficheiro de capa de uma pasta (mesmo esquema no cache e no durável)."""
    if _is_local_folder_id(folder_id):
        return f"lfolder_{hashlib.md5(folder_id.encode()).hexdigest()[:16]}.jpg"
    return f"{folder_id}.jpg"

def _restore_custom_cover(folder_id: str, cp: Path) -> bool:
    """Se houver capa manual guardada em data/custom_covers, repõe-na no cache."""
    src = CUSTOM_COVERS / _cover_key(folder_id)
    if src.exists():
        shutil.copy(src, cp)
        return True
    return False

def _cover_resp(request: Request, path: Path):
    """Capa de pasta é MUTÁVEL (o utilizador pode trocá-la), então não pode levar
    max-age longo — o browser guardaria a antiga por uma semana e a troca "não
    pegaria". no-cache + ETag: revalida sempre, mas custa só um 304 na LAN."""
    st = path.stat()
    etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
    headers = {"Cache-Control": "no-cache", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(path.read_bytes(), media_type="image/jpeg", headers=headers)

@app.get("/api/folders/{folder_id:path}/cover")
def folder_cover(folder_id: str, request: Request):
    from pathlib import Path

    # Detecta se é pasta local (Windows C:\ ou Unix /)
    is_local = _is_local_folder_id(folder_id)

    if is_local:
        # ── LOCAL: trata completamente separado do Drive ──
        cp = MAIN_COVERS / _cover_key(folder_id)
        if cp.exists():
            return _cover_resp(request, cp)
        if _restore_custom_cover(folder_id, cp):
            return _cover_resp(request, cp)
        first_path = lc.peek_folder_cover(folder_id)
        if not first_path:
            raise HTTPException(404)
        try:
            filename = Path(first_path).name
            data = Path(first_path).read_bytes()
            cover = _thumb(extract_cover(data, filename))
            if cover:
                cp.write_bytes(cover)
                return _cover_resp(request, cp)
        except Exception as e:
            print(f"[cover] Erro local '{Path(first_path).name}': {e}")
        raise HTTPException(404)

    # ── DRIVE ──
    cp = MAIN_COVERS / _cover_key(folder_id)
    if cp.exists():
        return _cover_resp(request, cp)
    if _restore_custom_cover(folder_id, cp):
        return _cover_resp(request, cp)

    if not drive.is_authenticated():
        raise HTTPException(401)

    result = drive.peek_folder_cover(folder_id)
    if not result:
        raise HTTPException(404)

    # Suporta drive_client antigo (str) e novo (tuple/list)
    if isinstance(result, (tuple, list)):
        first_id, filename = result[0], result[1]
    else:
        first_id = result
        _info = drive.get_file_info(first_id)
        filename = _info.get("name", "unknown.cbz")

    cc = COVER_CACHE / f"{first_id}.jpg"
    if cc.exists():
        shutil.copy(cc, cp)
        return _cover_resp(request, cp)

    cover = _get_cover(first_id, filename)
    if cover:
        cp.write_bytes(cover)
        cc.write_bytes(cover)
        return _cover_resp(request, cp)
    raise HTTPException(404)

@app.post("/api/folders/{folder_id:path}/cover/refresh")
def folder_cover_refresh(folder_id: str):
    """
    Força re-geração da capa de uma pasta:
    1. Apaga capa cacheada
    2. Re-corre peek com depth=8 (mais fundo que o normal)
    3. Devolve nova capa ou 404 se nada encontrado
    """
    from pathlib import Path

    is_local = _is_local_folder_id(folder_id)

    if is_local:
        cp = MAIN_COVERS / _cover_key(folder_id)
        cp.unlink(missing_ok=True)  # apaga cache antiga
        # Atualizar = voltar à capa automática: descarta também a capa manual guardada
        (CUSTOM_COVERS / _cover_key(folder_id)).unlink(missing_ok=True)
        first_path = lc.peek_folder_cover(folder_id, depth=8)
        if not first_path:
            raise HTTPException(404, "Nenhum ficheiro de HQ encontrado")
        try:
            filename = Path(first_path).name
            data = Path(first_path).read_bytes()
            cover = _thumb(extract_cover(data, filename))
            if cover:
                cp.write_bytes(cover)
                return _br(cover)
        except Exception as e:
            print(f"[cover refresh] Erro local '{Path(first_path).name}': {e}")
        raise HTTPException(404)

    # ── DRIVE ──
    if not drive.is_authenticated():
        raise HTTPException(401)

    cp = MAIN_COVERS / _cover_key(folder_id)
    cp.unlink(missing_ok=True)  # apaga cache antiga
    # Atualizar = voltar à capa automática: descarta também a capa manual guardada
    (CUSTOM_COVERS / _cover_key(folder_id)).unlink(missing_ok=True)

    result = drive.peek_folder_cover(folder_id, depth=8)
    if not result:
        raise HTTPException(404, "Nenhum ficheiro de HQ encontrado")

    first_id = result
    try:
        _info = drive.get_file_info(first_id)
        filename = _info.get("name", "unknown.cbz")
    except Exception:
        filename = "unknown.cbz"

    cc = COVER_CACHE / f"{first_id}.jpg"
    if cc.exists():
        shutil.copy(cc, cp)
        return _fr(cp)

    cover = _get_cover(first_id, filename)
    if cover:
        cp.write_bytes(cover)
        cc.write_bytes(cover)
        return _br(cover)
    raise HTTPException(404)


@app.post("/api/folders/{folder_id:path}/cover/upload")
async def folder_cover_upload(folder_id: str, file: UploadFile):
    """
    Define manualmente a capa de uma pasta com uma imagem carregada pelo utilizador.
    Aceita JPEG, PNG, WEBP, etc. — converte sempre para JPEG.
    """
    from PIL import Image
    import io as _io

    cp = MAIN_COVERS / _cover_key(folder_id)

    try:
        raw = await file.read()
        img = Image.open(_io.BytesIO(raw)).convert("RGB")
        # Crop to 2:3 ratio (standard comic cover)
        w, h = img.size
        target_ratio = 2 / 3
        current_ratio = w / h
        if current_ratio > target_ratio:
            new_w = int(h * target_ratio)
            img = img.crop(((w - new_w) // 2, 0, (w - new_w) // 2 + new_w, h))
        elif current_ratio < target_ratio:
            new_h = int(w / target_ratio)
            img = img.crop((0, (h - new_h) // 2, w, (h - new_h) // 2 + new_h))
        img = img.resize((300, 450), Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, "JPEG", quality=88, optimize=True)
        jpeg = buf.getvalue()
    except Exception as e:
        raise HTTPException(400, f"Imagem inválida: {e}")

    cp.write_bytes(jpeg)
    # Cópia durável fora do cache: a capa manual não depende do ficheiro
    # original nem de cache/ — sobrevive a limpezas e é reposta sozinha.
    (CUSTOM_COVERS / _cover_key(folder_id)).write_bytes(jpeg)
    return _br(jpeg)

@app.get("/api/comics/{file_id}/cover")
def comic_cover(file_id: str):
    cp = COVER_CACHE / f"{file_id}.jpg"
    if cp.exists(): return _fr(cp)
    info = _get_info(file_id)
    filename = _effective_name(info)
    cover = _get_cover(file_id, filename)
    if cover: cp.write_bytes(cover); return _br(cover)
    raise HTTPException(404)

# ── Pages ────────────────────────────────────────────────────────────────────
@app.get("/api/comics/{file_id}/info")
def comic_info(file_id: str, background_tasks: BackgroundTasks,
               pid: str | None = Depends(_profile_opt)):
    info = _get_info(file_id)
    filename = _effective_name(info)
    if lc.is_local(file_id):
        p = lc.id_to_path(file_id)
        pages = get_page_count_path(p) if p else 0
    else:
        data = _get_data(file_id, filename)
        pages = get_page_count(data, filename)
        background_tasks.add_task(_evict)
    background_tasks.add_task(_bg_pregen, file_id, filename, 0, 7)
    _pc_set(file_id, pages)
    return {"id": file_id, "name": info["name"], "pages": pages,
            "saved_page": rdg.get_saved_page(pid, file_id) if pid else 0}

@app.get("/api/comics/{file_id}/pages")
def comic_pages(file_id: str, pid: str | None = Depends(_profile_opt)):
    """Contagem de páginas p/ tooltip de hover. Persiste o resultado (fica
    instantâneo depois). Drive não-cacheado usa contagem PARCIAL barata
    (PDF: 2 MB; CBZ: cauda) — nunca baixa o ficheiro inteiro."""
    cached = _PAGE_COUNTS.get(file_id)
    if cached:
        return {"pages": cached}
    saved = (rdg.get_state(pid).get("in_progress", {}).get(file_id) or {}) if pid else {}
    if saved.get("pages"):
        _pc_set(file_id, saved["pages"]); return {"pages": int(saved["pages"])}
    if lc.is_local(file_id):
        p = lc.id_to_path(file_id)
        n = get_page_count_path(p) if p else None
        _pc_set(file_id, n); return {"pages": n}
    import glob
    matches = glob.glob(str(_ROOT / "cache/comics" / (file_id + ".*")))
    if matches:
        try:
            # Nome do cache pode ter extensão enganosa (extensionless vira .cbz):
            # passa nome vazio para o get_page_count detectar pelo conteúdo (sniff).
            n = get_page_count(Path(matches[0]).read_bytes(), "")
            _pc_set(file_id, n); return {"pages": n}
        except Exception:
            pass
    # Drive não-cacheado: contagem parcial barata
    try:
        info = _get_info(file_id)
        with _EXTRACT_SEM:
            n = get_page_count_partial(file_id, info.get("name", "x"), drive)
        _pc_set(file_id, n); return {"pages": n}
    except Exception:
        return {"pages": None}

@app.get("/api/comics/{file_id}/page/{page_num}")
def comic_page(file_id: str, page_num: int, background_tasks: BackgroundTasks):
    pd = COVER_CACHE / f"pages_{file_id}"; pd.mkdir(exist_ok=True)
    pc = pd / f"{page_num}.jpg"
    info = _get_info(file_id)
    filename = _effective_name(info)
    if pc.exists():
        background_tasks.add_task(_bg_pregen, file_id, filename, page_num+1, 5)
        return _fr(pc, CACHE_1DAY)
    if lc.is_local(file_id):
        p = lc.id_to_path(file_id)
        with _EXTRACT_SEM:
            page = extract_page_path(p, page_num) if p else None
    else:
        data = _get_data(file_id, filename)
        with _EXTRACT_SEM:
            page = extract_page(data, filename, page_num)
    if page:
        pc.write_bytes(page)
        background_tasks.add_task(_bg_pregen, file_id, filename, page_num+1, 5)
        return _br(page, CACHE_1DAY)
    raise HTTPException(404)

# ── Cache utils ───────────────────────────────────────────────────────────────
@app.get("/api/cache/status")
def cache_status():
    d = _ROOT/"cache/comics"
    size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1024**3 if d.exists() else 0
    max_gb = float(os.getenv("CACHE_MAX_GB","15"))
    return {"comics_gb": round(size,2), "max_gb": max_gb,
            "covers_cached": len(list(COVER_CACHE.glob("*.jpg"))),
            "main_covers_cached": len(list(MAIN_COVERS.glob("*.jpg")))}

@app.post("/api/cache/evict")
def cache_evict():
    _evict(); return {"ok": True}

@app.post("/api/warmup")
def warmup(background_tasks: BackgroundTasks, folder_id: str | None = None):
    if not drive.is_authenticated(): raise HTTPException(401)
    def _do(fid):
        try:
            items = drive.list_items(fid)
            for f in items["folders"]:
                cp = MAIN_COVERS/f"{f['id']}.jpg"
                if not cp.exists():
                    r = drive.peek_folder_cover(f["id"])
                    if r:
                        fid2 = r  # peek_folder_cover returns str (file_id)
                        try:
                            _info = drive.get_file_info(fid2)
                            fname = _info.get("name", "unknown.cbz")
                        except Exception:
                            fname = "unknown.cbz"
                        cc = COVER_CACHE/f"{fid2}.jpg"
                        if cc.exists(): shutil.copy(cc, cp)
                        else:
                            cov = _thumb(extract_cover_partial(fid2, fname, drive))
                            if cov: cp.write_bytes(cov); cc.write_bytes(cov)
                _do(f["id"])
            for c in items["comics"]:
                cp = COVER_CACHE/f"{c['id']}.jpg"
                if not cp.exists():
                    info = drive.get_file_info(c["id"])
                    fn = info.get("name", "unknown.cbz")
                    cov = _thumb(extract_cover_partial(c["id"], fn, drive))
                    if cov: cp.write_bytes(cov)
        except Exception as e:
            print(f"[warmup] {e}")
    roots = [folder_id] if folder_id else [f["drive_id"] for f in cfg_mgr.get_folders() if f["type"]=="drive"]
    for r in roots: background_tasks.add_task(_do, r)
    return {"ok": True}


# ── Listas personalizadas ──────────────────────────────────────────────────────

@app.get("/api/lists")
def get_lists(pid: str = Depends(_profile)):
    return rdg.get_lists(pid)

class ListCreate(BaseModel):
    name: str

class ListRename(BaseModel):
    name: str

class ListAdd(BaseModel):
    file_id: str
    name: str
    is_folder: bool = False

@app.post("/api/lists")
def create_list(b: ListCreate, pid: str = Depends(_profile)):
    return rdg.create_list(pid, b.name)

@app.put("/api/lists/{list_id}")
def rename_list(list_id: str, b: ListRename, pid: str = Depends(_profile)):
    rdg.rename_list(pid, list_id, b.name)
    return {"ok": True}

@app.delete("/api/lists/{list_id}")
def delete_list(list_id: str, pid: str = Depends(_profile)):
    rdg.delete_list(pid, list_id)
    return {"ok": True}

@app.post("/api/lists/{list_id}/comics")
def add_to_list(list_id: str, b: ListAdd, pid: str = Depends(_profile)):
    rdg.add_to_list(pid, list_id, b.file_id, b.name, b.is_folder)
    return {"ok": True}

@app.delete("/api/lists/{list_id}/comics/{file_id:path}")
def remove_from_list(list_id: str, file_id: str, pid: str = Depends(_profile)):
    rdg.remove_from_list(pid, list_id, file_id)
    return {"ok": True}

# ── Estatísticas ───────────────────────────────────────────────────────────────

@app.get("/api/stats")
def get_stats(pid: str = Depends(_profile)):
    return rdg.get_stats(pid)

# ── Pesquisa local ─────────────────────────────────────────────────────────────

@app.get("/api/local/search")
def local_search(path: str, q: str = Query(..., min_length=2)):
    results = []
    p = Path(path)
    q_lower = q.lower()
    try:
        for item in p.rglob("*"):
            if item.is_file() and item.suffix.lower() in lc.COMIC_EXTS:
                if q_lower in item.name.lower():
                    fid = lc.path_to_id(str(item))
                    results.append({"id": fid, "name": item.name,
                                    "size": item.stat().st_size})
                    if len(results) >= 60:
                        break
    except Exception as e:
        print(f"[local search] {e}")
    return {"results": results}

# ── Frontend ──────────────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent.parent / "static"

@app.get("/", include_in_schema=False)
def serve_index():
    """
    Serve index.html com headers no-cache.
    Garante que actualizações ao HTML são sempre visíveis sem precisar
    de limpar cache do browser ou bumpar versão do Service Worker.
    """
    return FileResponse(
        str(STATIC_DIR / "index.html"),
        media_type="text/html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn, webbrowser, threading, time
    host = os.getenv("HOST", "0.0.0.0")   # 0.0.0.0 = acessível na rede (PC + iPhone)
    port = int(os.getenv("PORT", "8000"))
    url = f"http://localhost:{port}"
    if os.getenv("NO_BROWSER") != "1":
        threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(url)), daemon=True).start()
    print(f"\n Omnivault em {url}\n")
    uvicorn.run("main:app", host=host, port=port, reload=False)
