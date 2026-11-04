"""
Google Drive client — OAuth 2.0 (read-only)
"""
import io
import os
import secrets
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Pasta dos dados (data/, cache/, credentials/). Padrão: raiz do projeto.
# OMNIVAULT_HOME permite guardar em outro lugar (e isola os testes).
_ROOT            = Path(os.getenv("OMNIVAULT_HOME") or Path(__file__).parent.parent)
CREDENTIALS_FILE = _ROOT / "credentials/credentials.json"
TOKEN_FILE       = _ROOT / "credentials/token.json"
SCOPES           = ["https://www.googleapis.com/auth/drive.readonly"]
REDIRECT_URI     = os.getenv("OAUTH_REDIRECT", f"http://localhost:{os.getenv('PORT','8000')}/auth/callback")

# Todas as extensões aceites
COMIC_EXTS = ["cbz", "cbr", "pdf", "zip", "rar", "cb7"]
_EXT_Q = " or ".join(
    f"name contains '.{e}'"
    for e in COMIC_EXTS + [e.upper() for e in COMIC_EXTS]
)

# Tipos MIME de HQ — usados quando o nome do ficheiro NÃO tem extensão
# (ex.: "Capítulo 01" no Drive, mas mimeType=application/pdf).
COMIC_MIMES = {
    "application/pdf",
    "application/zip", "application/x-cbz", "application/vnd.comicbook+zip",
    "application/x-cbr", "application/vnd.comicbook-rar",
    "application/x-rar-compressed", "application/vnd.rar",
    "application/x-7z-compressed",
}

def _is_comic(name: str, mime: str) -> bool:
    n = (name or "").lower()
    return any(n.endswith(f".{e}") for e in COMIC_EXTS) or (mime in COMIC_MIMES)

_pending_flows: dict[str, Flow] = {}


class DriveClient:
    def __init__(self):
        self.creds: Credentials | None = None
        self._load_token()

    # ── Auth ─────────────────────────────────────────────────────────────────

    def _load_token(self):
        if not TOKEN_FILE.exists():
            return
        self.creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if self.creds and self.creds.expired and self.creds.refresh_token:
            try:
                self.creds.refresh(Request())
                self._save_token()
            except Exception as e:
                # NÃO zeramos as credenciais numa falha aqui. Uma falha transitória
                # (ex.: servidor sobe antes da rede subir) não significa token inválido;
                # se zerássemos, o Drive ficaria morto até reiniciar o processo. Mantemos
                # o token e deixamos o auto-refresh de is_authenticated()/download_range()
                # recuperar quando a rede voltar. Se o refresh token estiver mesmo revogado,
                # creds.valid continua False → o app pede reconexão normalmente.
                print(f"[auth] Token refresh no arranque falhou (mantido p/ retry): {e}")

    def _save_token(self):
        TOKEN_FILE.parent.mkdir(exist_ok=True)
        TOKEN_FILE.write_text(self.creds.to_json())

    def is_authenticated(self) -> bool:
        """Conectado = temos credenciais utilizáveis.

        O access token expira a cada ~1h; antes só renovávamos no arranque do
        servidor, então /auth/status dizia "desconectado" para quem abrisse
        horas depois (ex.: iPad) mesmo com o refresh token válido. Agora
        renovamos aqui — configurou 1x, vale para todos os aparelhos."""
        if self.creds and self.creds.expired and self.creds.refresh_token:
            try:
                self.creds.refresh(Request())
                self._save_token()
            except Exception as e:
                print(f"[auth] Token refresh failed: {e}")
        return self.creds is not None and self.creds.valid

    def logout(self):
        """Remove o token guardado e limpa as credenciais em memória."""
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
        self.creds = None

    def get_auth_url(self) -> str:
        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                "credentials/credentials.json não encontrado. Vê o README."
            )
        state = secrets.token_urlsafe(16)
        flow = Flow.from_client_secrets_file(
            str(CREDENTIALS_FILE), scopes=SCOPES, redirect_uri=REDIRECT_URI,
        )
        auth_url, _ = flow.authorization_url(
            state=state, prompt="consent", access_type="offline"
        )
        _pending_flows[state] = flow
        return auth_url

    def exchange_code(self, code: str, state: str):
        flow = _pending_flows.pop(state, None)
        if not flow:
            raise ValueError(f"OAuth state inválido: {state}")
        flow.fetch_token(code=code)
        self.creds = flow.credentials
        self._save_token()

    # ── Drive API ─────────────────────────────────────────────────────────────

    def _svc(self):
        return build("drive", "v3", credentials=self.creds, cache_discovery=False)

    def list_items(self, folder_id: str) -> dict:
        svc = self._svc()

        # Subpastas
        folders_resp = svc.files().list(
            q=(f"'{folder_id}' in parents "
               f"and mimeType='application/vnd.google-apps.folder' "
               f"and trashed=false"),
            fields="files(id, name, modifiedTime)",
            orderBy="name",
            pageSize=200,
        ).execute()

        # Ficheiros de HQ — pagina até buscar tudo.
        # NÃO usamos "name contains '.cbz'..." porque o índice do Drive não casa
        # extensões de CBZ/CBR (ficam como application/octet-stream). Em vez disso
        # listamos todos os ficheiros (não-pasta, não-shortcut) e filtramos a
        # extensão no cliente — igual ao fallback do peek_folder_cover.
        comics, page_token = [], None
        while True:
            resp = svc.files().list(
                q=(f"'{folder_id}' in parents "
                   f"and mimeType != 'application/vnd.google-apps.folder' "
                   f"and mimeType != 'application/vnd.google-apps.shortcut' "
                   f"and trashed=false"),
                fields="nextPageToken, files(id, name, size, modifiedTime, mimeType)",
                orderBy="name",
                pageSize=200,
                pageToken=page_token,
            ).execute()
            for f in resp.get("files", []):
                if _is_comic(f.get("name", ""), f.get("mimeType", "")):
                    comics.append(f)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return {"folders": folders_resp.get("files", []), "comics": comics}

    def search_comics(self, query: str) -> list:
        """Pesquisa por nome em todo o Drive."""
        svc = self._svc()
        safe_q = query.replace("'", "\\'")
        # Procura por nome e filtra HQ por extensão OU mimeType no cliente,
        # para apanhar também ficheiros sem extensão no nome (ex.: "Capítulo 01").
        results, page_token = [], None
        while True:
            resp = svc.files().list(
                q=(f"name contains '{safe_q}' "
                   f"and mimeType != 'application/vnd.google-apps.folder' "
                   f"and mimeType != 'application/vnd.google-apps.shortcut' "
                   f"and trashed=false"),
                fields="nextPageToken, files(id, name, size, modifiedTime, mimeType)",
                orderBy="name",
                pageSize=100,
                pageToken=page_token,
            ).execute()
            for f in resp.get("files", []):
                if _is_comic(f.get("name", ""), f.get("mimeType", "")):
                    results.append(f)
            page_token = resp.get("nextPageToken")
            if not page_token or len(results) >= 80:
                break
        return results

    def get_file_info(self, file_id: str) -> dict:
        return self._svc().files().get(
            fileId=file_id,
            fields="id, name, size, mimeType",
        ).execute()

    def download_file(self, file_id: str, filename: str, skip_cache: bool = False) -> bytes:
        """
        Descarrega um ficheiro do Drive.
        skip_cache=True: não guarda em cache/comics/ (ex: extracção de capa CBR).
        skip_cache=False: guarda para leitura posterior (default).
        Se o ficheiro já estiver em cache, usa sempre independentemente de skip_cache.
        """
        cache_dir = _ROOT / "cache/comics"
        cache_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(filename).suffix.lower() or ".cbz"
        cache_path = cache_dir / f"{file_id}{ext}"

        if cache_path.exists():
            return cache_path.read_bytes()

        print(f"[download] {filename}")
        request = self._svc().files().get_media(fileId=file_id)
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, request, chunksize=10 * 1024 * 1024)
        done = False
        while not done:
            status, done = dl.next_chunk()
            if status:
                print(f"[download] {int(status.progress() * 100)}%")

        data = buf.getvalue()
        if not skip_cache:
            cache_path.write_bytes(data)
        print(f"[download] OK{'(no-cache)' if skip_cache else ''}: {filename} ({len(data)/1024/1024:.1f} MB)")
        return data

    def peek_folder_cover(self, folder_id: str, depth: int = 5) -> str | None:
        """
        Devolve o file_id do primeiro comic dentro de uma pasta (recursivo, até depth=5).
        Usa fullText=false para ser mais rápido e não filtrar por extensão no primeiro nível
        (Drive às vezes não indexa extensões em drives partilhados).
        """
        if depth < 0:
            return None
        svc = self._svc()

        # Tenta primeiro com query de extensões
        try:
            resp = svc.files().list(
                q=f"'{folder_id}' in parents and ({_EXT_Q}) and trashed=false",
                fields="files(id, name)",
                pageSize=1,
                orderBy="name",
            ).execute()
            files = resp.get("files", [])
            if files:
                return files[0]["id"]
        except Exception as e:
            print(f"[peek] Query com extensões falhou para {folder_id}: {e}")

        # Se não encontrou, tenta qualquer ficheiro não-pasta (fallback)
        try:
            resp2 = svc.files().list(
                q=(f"'{folder_id}' in parents "
                   f"and mimeType != 'application/vnd.google-apps.folder' "
                   f"and mimeType != 'application/vnd.google-apps.shortcut' "
                   f"and trashed=false"),
                fields="files(id, name, mimeType)",
                pageSize=10,
                orderBy="name",
            ).execute()
            for f in resp2.get("files", []):
                if _is_comic(f.get("name", ""), f.get("mimeType", "")):
                    return f["id"]
        except Exception:
            pass

        # Recursão em subpastas
        try:
            sub_resp = svc.files().list(
                q=(f"'{folder_id}' in parents "
                   f"and mimeType='application/vnd.google-apps.folder' "
                   f"and trashed=false"),
                fields="files(id, name)",
                pageSize=10,
                orderBy="name",
            ).execute()
            for sub in sub_resp.get("files", []):
                result = self.peek_folder_cover(sub["id"], depth - 1)
                if result:
                    return result
        except Exception as e:
            print(f"[peek] Subpastas falhou para {folder_id}: {e}")

        return None

    def download_range(self, file_id: str, start: int, end: int) -> bytes:
        """
        Descarrega apenas os bytes [start, end] via HTTP Range request.
        Usa requests + token OAuth directamente — sem bibliotecas intermediárias.
        """
        import requests as req_lib

        # Refresh token se necessário
        if self.creds.expired and self.creds.refresh_token:
            self.creds.refresh(Request())
            self._save_token()

        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        headers = {
            "Authorization": f"Bearer {self.creds.token}",
            "Range": f"bytes={start}-{end}",
        }
        resp = req_lib.get(url, headers=headers, timeout=30)
        # 206 Partial Content é o sucesso esperado; 200 também é válido
        if resp.status_code not in (200, 206):
            raise IOError(f"Range request falhou: HTTP {resp.status_code}")
        return resp.content
