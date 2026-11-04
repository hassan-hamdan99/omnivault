"""
Extrai capas e páginas de CBZ, CBR e PDF.

CBZ  → zipfile nativo (Python stdlib)
CBR  → 7-Zip subprocess (Windows) ou rarfile + unrar (Linux/Mac)
PDF  → PyMuPDF (fitz)
"""
import io
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from PIL import Image

# Silencia MuPDF
try:
    import fitz as _f
    _f.TOOLS.mupdf_display_errors(False)
    _f.TOOLS.mupdf_display_warnings(False)
except Exception:
    pass

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}

def _is_image(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_EXTS

def _sorted_images(names) -> list[str]:
    return sorted(n for n in names if _is_image(n) and "__MACOSX" not in n)

def _to_jpeg(data: bytes, quality: int = 88) -> bytes:
    img = Image.open(io.BytesIO(data))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


# ── 7-Zip detection ───────────────────────────────────────────────────────────

def _find_tool(names: list[str], win_paths: list[str]) -> str | None:
    for p in win_paths:
        if Path(p).exists():
            return p
    for n in names:
        found = shutil.which(n)
        if found:
            return found
    return None

_7Z = _find_tool(
    ["7z", "7z.exe", "7za", "7za.exe"],
    [r"C:\Program Files\7-Zip\7z.exe",
     r"C:\Program Files (x86)\7-Zip\7z.exe"]
)

_UNRAR = _find_tool(
    ["unrar", "unrar.exe"],
    [r"C:\Program Files\WinRAR\UnRAR.exe",
     r"C:\Program Files (x86)\WinRAR\UnRAR.exe"]
)

if _7Z:
    print(f"[rar] 7-Zip: {_7Z}")
if _UNRAR:
    print(f"[rar] UnRAR: {_UNRAR}")
if not _7Z and not _UNRAR:
    print("[rar] AVISO: Nem 7-Zip nem UnRAR encontrados — CBR não funcionará.")
    print("[rar] Instala 7-Zip: https://www.7-zip.org")


# ── CBR/RAR via subprocess ────────────────────────────────────────────────────

def _list_archive(archive_path: str) -> list[str]:
    """Lista ficheiros dentro de um archive (RAR/CBR) via 7z ou unrar."""
    if _7Z:
        # -sccUTF-8: sem isso o 7z escreve no codepage do console (cp850/cp1252)
        # e nomes acentuados chegam mutilados — a extração por nome falha depois.
        r = subprocess.run(
            [_7Z, "l", "-ba", "-slt", "-sccUTF-8", archive_path],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30
        )
        images = []
        for line in r.stdout.splitlines():
            if line.startswith("Path = "):
                fname = line[7:].strip()
                if _is_image(fname) and "__MACOSX" not in fname:
                    images.append(fname)
        return sorted(images)

    if _UNRAR:
        r = subprocess.run(
            [_UNRAR, "lb", archive_path],
            capture_output=True, text=True, errors="replace", timeout=30
        )
        return sorted(
            l.strip() for l in r.stdout.splitlines()
            if _is_image(l.strip()) and "__MACOSX" not in l
        )

    return []


def _extract_file_from_archive(archive_path: str, member: str, out_dir: str) -> bytes | None:
    """Extrai um ficheiro específico de um archive para out_dir."""
    if _7Z:
        subprocess.run(
            [_7Z, "e", archive_path, member, f"-o{out_dir}", "-y"],
            capture_output=True, timeout=60
        )
    elif _UNRAR:
        subprocess.run(
            [_UNRAR, "e", "-y", "-inul", archive_path, member, out_dir],
            capture_output=True, timeout=60
        )
    else:
        return None

    # Lê o ficheiro extraído (7z extrai só o basename)
    basename = Path(member).name
    out_file = Path(out_dir) / basename
    if out_file.exists():
        return out_file.read_bytes()

    # Fallback: pega qualquer ficheiro de imagem que exista
    extracted = [f for f in Path(out_dir).rglob("*") if f.is_file() and _is_image(f.name)]
    if extracted:
        return extracted[0].read_bytes()

    return None


def _extract_nth_full(archive_path: str, page_num: int, tmp: str) -> bytes | None:
    """Fallback por POSIÇÃO: alguns RAR antigos guardam nomes numa codificação
    que nem o 7z decodifica ('Aniquila??o...jpg') — extração por nome é
    impossível. Extrai tudo e devolve a n-ésima imagem em ordem de nome
    (mesma ordenação da _list_archive)."""
    out_dir = Path(tmp) / "full"
    out_dir.mkdir(exist_ok=True)
    _extract_all_from_archive(archive_path, str(out_dir))
    imgs = sorted(
        (f for f in out_dir.rglob("*") if f.is_file() and _is_image(f.name)),
        key=lambda f: f.name)
    if page_num < len(imgs):
        return imgs[page_num].read_bytes()
    return None


def _extract_all_from_archive(archive_path: str, out_dir: str):
    """Extrai todos os ficheiros de um archive para out_dir."""
    if _7Z:
        subprocess.run(
            [_7Z, "e", archive_path, f"-o{out_dir}", "-y"],
            capture_output=True, timeout=120
        )
    elif _UNRAR:
        subprocess.run(
            [_UNRAR, "e", "-y", "-inul", archive_path, out_dir],
            capture_output=True, timeout=120
        )


def _cover_cbr(data: bytes) -> bytes | None:
    if not _7Z and not _UNRAR:
        raise RuntimeError("Nenhuma ferramenta RAR disponível")

    with tempfile.TemporaryDirectory() as tmp:
        cbr = Path(tmp) / "c.cbr"
        cbr.write_bytes(data)
        images = _list_archive(str(cbr))
        if not images:
            return None
        out_dir = Path(tmp) / "out"
        out_dir.mkdir()
        raw = _extract_file_from_archive(str(cbr), images[0], str(out_dir)) \
              or _extract_nth_full(str(cbr), 0, tmp)
        if raw:
            return _to_jpeg(raw)
    return None


def _page_cbr(data: bytes, page_num: int) -> bytes | None:
    if not _7Z and not _UNRAR:
        raise RuntimeError("Nenhuma ferramenta RAR disponível")

    with tempfile.TemporaryDirectory() as tmp:
        cbr = Path(tmp) / "c.cbr"
        cbr.write_bytes(data)
        images = _list_archive(str(cbr))
        if page_num >= len(images):
            return None
        out_dir = Path(tmp) / "out"
        out_dir.mkdir()
        raw = _extract_file_from_archive(str(cbr), images[page_num], str(out_dir)) \
              or _extract_nth_full(str(cbr), page_num, tmp)
        if raw:
            return _to_jpeg(raw, quality=92)
    return None


# ── CBZ ───────────────────────────────────────────────────────────────────────

def _cover_cbz(data: bytes) -> bytes | None:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        images = _sorted_images(z.namelist())
        if not images:
            return None
        return _to_jpeg(z.read(images[0]))

def _page_cbz(data: bytes, page_num: int) -> bytes | None:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        images = _sorted_images(z.namelist())
        if page_num >= len(images):
            return None
        return _to_jpeg(z.read(images[page_num]), quality=92)


# ── PDF ───────────────────────────────────────────────────────────────────────

def _cover_pdf(data: bytes) -> bytes | None:
    import fitz
    doc = fitz.open(stream=data, filetype="pdf")
    if doc.page_count == 0:
        return None
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
    return _to_jpeg(pix.tobytes("png"))

def _page_pdf(data: bytes, page_num: int) -> bytes | None:
    import fitz
    doc = fitz.open(stream=data, filetype="pdf")
    if page_num >= doc.page_count:
        return None
    pix = doc[page_num].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
    return _to_jpeg(pix.tobytes("png"), quality=92)


# ═══════════════════════════════════════════════════════════════════════════════
# API pública
# ═══════════════════════════════════════════════════════════════════════════════

def _dispatch_cover(data: bytes, ext: str) -> bytes | None:
    if ext in (".cbz", ".zip"):
        return _cover_cbz(data)
    elif ext in (".cbr", ".rar"):
        return _cover_cbr(data)
    elif ext == ".pdf":
        return _cover_pdf(data)
    else:
        # Sem extensão reconhecida — tenta todos
        for fn in (_cover_cbz, _cover_cbr, _cover_pdf):
            try:
                r = fn(data)
                if r:
                    return r
            except Exception:
                continue
    return None

def _dispatch_page(data: bytes, ext: str, page_num: int) -> bytes | None:
    if ext in (".cbz", ".zip"):
        return _page_cbz(data, page_num)
    elif ext in (".cbr", ".rar"):
        return _page_cbr(data, page_num)
    elif ext == ".pdf":
        return _page_pdf(data, page_num)
    return None


_KNOWN_EXTS = {".cbz", ".zip", ".cbr", ".rar", ".pdf", ".cb7"}

def _sniff_ext(data: bytes) -> str:
    """Deteta o formato pela assinatura dos bytes (para ficheiros sem extensão
    no nome, ex.: 'Capítulo 01' no Drive com mimeType application/pdf)."""
    if not data:
        return ""
    head = data[:8]
    if head[:4] == b"%PDF":
        return ".pdf"
    if head[:4] == b"Rar!":
        return ".cbr"
    if head[:6] == b"7z\xbc\xaf\x27\x1c":
        return ".cb7"
    if head[:2] == b"PK":
        return ".cbz"
    return ""

def _effective_ext(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext in _KNOWN_EXTS:
        return ext
    return _sniff_ext(data) or ext


def extract_cover(data: bytes, filename: str) -> bytes | None:
    ext = _effective_ext(filename, data)
    try:
        return _dispatch_cover(data, ext)
    except Exception as e:
        print(f"[extractor] Erro na capa de '{filename}': {e}")
    return None


def extract_cover_partial(file_id: str, filename: str, drive_client) -> bytes | None:
    """Extrai capa sem descarregar o ficheiro completo (só para Drive)."""
    from local_client import is_local
    ext = Path(filename).suffix.lower()

    # Ficheiros locais: leitura directa do disco, sem Range requests
    if is_local(file_id):
        try:
            data = drive_client.get_file_data(file_id) if hasattr(drive_client, 'get_file_data') else None
            if data is None:
                from local_client import get_file_data
                data = get_file_data(file_id)
            return extract_cover(data, filename)
        except Exception as e:
            print(f"[extractor] Erro na capa local de '{filename}': {e}")
        return None

    # Drive: tenta extracção parcial para CBZ/PDF, download completo para CBR
    try:
        if ext in (".cbz", ".zip"):
            return _cover_cbz_partial(file_id, filename, drive_client)
        elif ext in (".cbr", ".rar"):
            # CBR não beneficia de Range (RAR não tem índice no fim).
            # skip_cache=True: não guarda em cache/comics/ só para extrair a capa.
            # O ficheiro completo só é cacheado quando o utilizador abre para ler.
            data = drive_client.download_file(file_id, filename, skip_cache=True)
            return extract_cover(data, filename)
        elif ext == ".pdf":
            return _cover_pdf_partial(file_id, filename, drive_client)
        else:
            data = drive_client.download_file(file_id, filename)
            return extract_cover(data, filename)
    except Exception as e:
        print(f"[extractor] Partial cover falhou para '{filename}': {e} — a tentar download completo")
    # Fallback
    try:
        data = drive_client.download_file(file_id, filename)
        return extract_cover(data, filename)
    except Exception as e2:
        print(f"[extractor] Fallback também falhou para '{filename}': {e2}")
    return None


def extract_page(data: bytes, filename: str, page_num: int) -> bytes | None:
    ext = _effective_ext(filename, data)
    try:
        return _dispatch_page(data, ext, page_num)
    except Exception as e:
        print(f"[extractor] Erro na página {page_num} de '{filename}': {e}")
    return None


def get_page_count(data: bytes, filename: str) -> int:
    ext = _effective_ext(filename, data)
    try:
        if ext in (".cbz", ".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                return len(_sorted_images(z.namelist()))
        elif ext in (".cbr", ".rar"):
            if not _7Z and not _UNRAR:
                return 0
            with tempfile.TemporaryDirectory() as tmp:
                cbr = Path(tmp) / "c.cbr"
                cbr.write_bytes(data)
                return len(_list_archive(str(cbr)))
        elif ext == ".pdf":
            import fitz
            return fitz.open(stream=data, filetype="pdf").page_count
    except Exception as e:
        print(f"[extractor] Erro na contagem de '{filename}': {e}")
    return 0


# ── Acesso por caminho (ficheiros locais) ──────────────────────────────────────
# Abre o ficheiro directamente do disco em vez de carregar todos os bytes em
# memória a cada página. Para CBR roda o 7-Zip sobre o ficheiro original (sem
# copiar o archive inteiro para um temporário).

def _cover_cbz_path(path: str) -> bytes | None:
    with zipfile.ZipFile(path) as z:
        images = _sorted_images(z.namelist())
        if not images:
            return None
        return _to_jpeg(z.read(images[0]))

def _page_cbz_path(path: str, page_num: int) -> bytes | None:
    with zipfile.ZipFile(path) as z:
        images = _sorted_images(z.namelist())
        if page_num >= len(images):
            return None
        return _to_jpeg(z.read(images[page_num]), quality=92)

def extract_cover_path(path: str) -> bytes | None:
    ext = Path(path).suffix.lower()
    try:
        if ext in (".cbz", ".zip"):
            return _cover_cbz_path(path)
        if ext in (".cbr", ".rar"):
            imgs = _list_archive(path)
            if not imgs:
                return None
            with tempfile.TemporaryDirectory() as tmp:
                raw = _extract_file_from_archive(path, imgs[0], tmp) \
                      or _extract_nth_full(path, 0, tmp)
                return _to_jpeg(raw) if raw else None
        if ext == ".pdf":
            import fitz
            doc = fitz.open(path)
            if doc.page_count == 0:
                return None
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            return _to_jpeg(pix.tobytes("png"))
    except Exception as e:
        print(f"[extractor] cover_path '{path}': {e}")
    return None

def extract_page_path(path: str, page_num: int) -> bytes | None:
    ext = Path(path).suffix.lower()
    try:
        if ext in (".cbz", ".zip"):
            return _page_cbz_path(path, page_num)
        if ext in (".cbr", ".rar"):
            imgs = _list_archive(path)
            if page_num >= len(imgs):
                return None
            with tempfile.TemporaryDirectory() as tmp:
                raw = _extract_file_from_archive(path, imgs[page_num], tmp) \
                      or _extract_nth_full(path, page_num, tmp)
                return _to_jpeg(raw, quality=92) if raw else None
        if ext == ".pdf":
            import fitz
            doc = fitz.open(path)
            if page_num >= doc.page_count:
                return None
            pix = doc[page_num].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            return _to_jpeg(pix.tobytes("png"), quality=92)
    except Exception as e:
        print(f"[extractor] page_path {page_num} '{path}': {e}")
    return None

def get_page_count_path(path: str) -> int:
    ext = Path(path).suffix.lower()
    try:
        if ext in (".cbz", ".zip"):
            with zipfile.ZipFile(path) as z:
                return len(_sorted_images(z.namelist()))
        if ext in (".cbr", ".rar"):
            return len(_list_archive(path))
        if ext == ".pdf":
            import fitz
            return fitz.open(path).page_count
    except Exception as e:
        print(f"[extractor] count_path '{path}': {e}")
    return 0


# ── CBZ partial (Range requests — só para Drive) ───────────────────────────────

def _cover_cbz_partial(file_id: str, filename: str, dc) -> bytes | None:
    info = dc.get_file_info(file_id)
    file_size = int(info.get("size", 0))
    if not file_size:
        raise ValueError("Tamanho desconhecido")

    tail_size = min(65536, file_size)
    tail = dc.download_range(file_id, file_size - tail_size, file_size - 1)

    eocd_pos = _find_eocd(tail)
    if eocd_pos < 0:
        raise ValueError("EOCD não encontrado no ZIP")

    eocd = tail[eocd_pos:]
    cd_size   = struct.unpack_from("<I", eocd, 12)[0]
    cd_offset = struct.unpack_from("<I", eocd, 16)[0]

    if cd_offset == 0xFFFFFFFF or cd_size == 0xFFFFFFFF:
        raise ValueError("ZIP64 não suportado em modo parcial")

    cd_bytes = dc.download_range(file_id, cd_offset, cd_offset + cd_size - 1)
    first_image = _parse_cd_first_image(cd_bytes)
    if not first_image:
        raise ValueError("Nenhuma imagem no CD")

    local_offset, compressed_size, compression, _ = first_image
    lhdr = dc.download_range(file_id, local_offset, local_offset + 29)
    fname_len = struct.unpack_from("<H", lhdr, 26)[0]
    extra_len = struct.unpack_from("<H", lhdr, 28)[0]
    data_start = local_offset + 30 + fname_len + extra_len

    compressed = dc.download_range(file_id, data_start, data_start + compressed_size - 1)

    if compression == 0:
        raw = compressed
    elif compression == 8:
        import zlib
        raw = zlib.decompress(compressed, -15)
    else:
        raise ValueError(f"Compressão {compression} não suportada")

    return _to_jpeg(raw)


def _find_eocd(data: bytes) -> int:
    sig = b'\x50\x4b\x05\x06'
    pos = len(data) - 22
    while pos >= 0:
        if data[pos:pos+4] == sig:
            return pos
        pos -= 1
    return -1


def _parse_cd_first_image(cd: bytes) -> tuple | None:
    CD_SIG = b'\x50\x4b\x01\x02'
    pos = 0
    entries = []
    while pos < len(cd) - 46:
        if cd[pos:pos+4] != CD_SIG:
            break
        compression     = struct.unpack_from("<H", cd, pos + 10)[0]
        compressed_size = struct.unpack_from("<I", cd, pos + 20)[0]
        fname_len       = struct.unpack_from("<H", cd, pos + 28)[0]
        extra_len       = struct.unpack_from("<H", cd, pos + 30)[0]
        comment_len     = struct.unpack_from("<H", cd, pos + 32)[0]
        local_offset    = struct.unpack_from("<I", cd, pos + 42)[0]
        fname_bytes     = cd[pos + 46: pos + 46 + fname_len]
        try:
            fname = fname_bytes.decode("utf-8")
        except Exception:
            fname = fname_bytes.decode("cp437", errors="replace")
        if _is_image(fname) and "__MACOSX" not in fname:
            entries.append((fname, local_offset, compressed_size, compression))
        pos += 46 + fname_len + extra_len + comment_len

    if not entries:
        return None
    entries.sort(key=lambda x: x[0])
    fname, local_offset, compressed_size, compression = entries[0]
    return (local_offset, compressed_size, compression, fname)


def _is_blank_jpeg(jpeg: bytes) -> bool:
    """Deteta capa praticamente em branco (ex.: PDF renderizado sem o conteúdo
    que estava além do chunk parcial baixado)."""
    if not jpeg:
        return True
    try:
        from PIL import ImageStat
        st = ImageStat.Stat(Image.open(io.BytesIO(jpeg)).convert("L"))
        return st.mean[0] > 240 and st.stddev[0] < 18
    except Exception:
        return False


def _cover_pdf_partial(file_id: str, filename: str, dc) -> bytes | None:
    info = dc.get_file_info(file_id)
    file_size = int(info.get("size", 1))
    end = min(2 * 1024 * 1024, file_size) - 1
    chunk = dc.download_range(file_id, 0, end)
    cover = _cover_pdf(chunk)
    # Se a 1ª página renderizou em branco, o conteúdo está além dos 2 MB:
    # baixa o ficheiro completo (sem cachear) e renderiza a sério.
    if _is_blank_jpeg(cover) and file_size > end + 1:
        try:
            data = dc.download_file(file_id, filename, skip_cache=True)
            full = _cover_pdf(data)
            if full and not _is_blank_jpeg(full):
                return full
            return full or cover
        except Exception as e:
            print(f"[extractor] PDF cover full fallback falhou '{filename}': {e}")
    return cover


# ── Contagem de páginas BARATA para Drive (sem download completo) ───────────────

def _count_cbz_partial(file_id: str, dc) -> int | None:
    """Conta imagens de um CBZ/ZIP no Drive lendo só o Central Directory (cauda)."""
    info = dc.get_file_info(file_id)
    size = int(info.get("size", 0))
    if not size:
        return None
    tail_size = min(65536, size)
    tail = dc.download_range(file_id, size - tail_size, size - 1)
    pos = _find_eocd(tail)
    if pos < 0:
        return None
    eocd = tail[pos:]
    cd_size = struct.unpack_from("<I", eocd, 12)[0]
    cd_offset = struct.unpack_from("<I", eocd, 16)[0]
    if cd_offset == 0xFFFFFFFF or cd_size == 0xFFFFFFFF:
        return None  # ZIP64 não suportado em modo parcial
    cd = dc.download_range(file_id, cd_offset, cd_offset + cd_size - 1)
    count, p = 0, 0
    while p < len(cd) - 46:
        if cd[p:p + 4] != b"\x50\x4b\x01\x02":
            break
        fname_len = struct.unpack_from("<H", cd, p + 28)[0]
        extra_len = struct.unpack_from("<H", cd, p + 30)[0]
        comment_len = struct.unpack_from("<H", cd, p + 32)[0]
        fname = cd[p + 46: p + 46 + fname_len].decode("utf-8", "replace")
        if _is_image(fname) and "__MACOSX" not in fname:
            count += 1
        p += 46 + fname_len + extra_len + comment_len
    return count or None


def get_page_count_partial(file_id: str, filename: str, dc) -> int | None:
    """Contagem de páginas sem baixar o ficheiro inteiro:
    PDF → abre os primeiros 2 MB (o PyMuPDF reconstrói a estrutura);
    CBZ → lê o Central Directory na cauda; CBR → None (precisa download)."""
    ext = Path(filename).suffix.lower()
    try:
        if ext in (".cbz", ".zip"):
            return _count_cbz_partial(file_id, dc)
        if ext in (".cbr", ".rar", ".cb7"):
            return None
        # .pdf ou sem extensão: tenta PDF parcial primeiro
        info = dc.get_file_info(file_id)
        size = int(info.get("size", 1))
        end = min(2 * 1024 * 1024, size) - 1
        chunk = dc.download_range(file_id, 0, end)
        try:
            import fitz
            doc = fitz.open(stream=chunk, filetype="pdf")
            if doc.page_count > 0:
                return doc.page_count
        except Exception:
            pass
        return _count_cbz_partial(file_id, dc)  # afinal era um CBZ sem extensão
    except Exception as e:
        print(f"[extractor] page_count_partial '{filename}': {e}")
    return None
