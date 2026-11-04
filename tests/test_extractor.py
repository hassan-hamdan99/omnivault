"""Extração: formatos, detecção por assinatura e leitura PARCIAL de PDF (Drive)."""
import io
import zipfile

import extractor
from extractor import fitz


def _pdf_with_images(pages=12) -> bytes:
    """PDF 'pesado' (imagens com ruído), para que os primeiros bytes não contenham
    o arquivo inteiro — como os PDFs de HQ reais."""
    import os
    from PIL import Image
    doc = fitz.open()
    for _ in range(pages):
        img = Image.frombytes("RGB", (300, 300), os.urandom(300 * 300 * 3))
        buf = io.BytesIO(); img.save(buf, "JPEG", quality=95)
        page = doc.new_page(width=300, height=450)
        page.insert_image(page.rect, stream=buf.getvalue())
    data = doc.tobytes()
    doc.close()
    return data


def test_pymupdf_version_reads_truncated_pdfs():
    """Trava de versão. O Drive usa só os primeiros 2 MB do PDF para capa e
    contagem de páginas. Com PDFs de HQ reais, PyMuPDF 1.24–1.26 abre o trecho
    truncado; 1.27+ recusa ("Invalid number of pages") e o app passa a baixar o
    arquivo INTEIRO só para a capa. Não suba sem validar com PDFs reais do Drive."""
    v = tuple(int(x) for x in fitz.VersionBind.split(".")[:2])
    assert v < (1, 27), f"PyMuPDF {fitz.VersionBind}: ver comentário em backend/requirements.txt"


def test_truncated_pdf_partial():
    """Capa e contagem a partir de um trecho inicial do PDF (caminho do Drive)."""
    data = _pdf_with_images()
    chunk = data[: len(data) // 2]
    cover = extractor._cover_pdf(chunk)
    assert cover and cover[:2] == b"\xff\xd8"
    assert fitz.open(stream=chunk, filetype="pdf").page_count > 0


def test_sniff_ext_by_signature():
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("a.txt", "x")
    assert extractor._sniff_ext(b"%PDF-1.7 ...") == ".pdf"
    assert extractor._sniff_ext(b"Rar!\x1a\x07\x00") == ".cbr"
    assert extractor._sniff_ext(b"7z\xbc\xaf\x27\x1c") == ".cb7"
    assert extractor._sniff_ext(zbuf.getvalue()) in (".cbz", ".zip")


def test_extract_from_bytes_without_extension():
    """Arquivo do Drive sem extensão no nome (ex.: 'Capítulo 01') é detectado pelos bytes."""
    data = _pdf_with_images(pages=2)
    assert extractor.get_page_count(data, "Capítulo 01") == 2
    assert extractor.extract_cover(data, "Capítulo 01")[:2] == b"\xff\xd8"
