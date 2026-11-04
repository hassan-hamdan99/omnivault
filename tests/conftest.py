"""Configuração dos testes.

OMNIVAULT_HOME aponta para uma pasta temporária ANTES de importar o backend: assim
data/, cache/ e credentials/ dos testes nunca tocam nos dados reais do usuário.
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

_HOME = Path(tempfile.mkdtemp(prefix="omnivault-test-"))
os.environ["OMNIVAULT_HOME"] = str(_HOME)
os.environ.pop("CORS_ORIGINS", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_HOME, ignore_errors=True)


def _jpeg(color, size=(240, 360)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture(scope="session")
def home() -> Path:
    return _HOME


@pytest.fixture(scope="session")
def library(tmp_path_factory) -> Path:
    """Biblioteca local de exemplo: Serie/ com um CBZ e um PDF de 3 páginas
    (e um CB7, se houver 7-Zip no sistema)."""
    root = tmp_path_factory.mktemp("biblioteca")
    serie = root / "Série Teste"
    serie.mkdir()

    with zipfile.ZipFile(serie / "Volume 01.cbz", "w") as z:
        for i, c in enumerate(["red", "green", "blue"]):
            z.writestr(f"{i + 1:03d}.jpg", _jpeg(c))

    from extractor import fitz      # pymupdf (ou fitz, em versões antigas)
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page(width=300, height=450)
        page.insert_text((40, 80), f"Pagina {i + 1}", fontsize=28)
    doc.save(serie / "Volume 02.pdf")
    doc.close()

    import extractor
    if extractor._7Z:
        src = root / "_cb7src"
        src.mkdir()
        for i, c in enumerate(["yellow", "purple"]):
            (src / f"{i + 1:03d}.jpg").write_bytes(_jpeg(c))
        subprocess.run([extractor._7Z, "a", "-t7z", str(serie / "Volume 03.cb7"),
                        str(src / "*.jpg")], check=True, capture_output=True)
        shutil.rmtree(src)
    return root


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(scope="session")
def pid(client) -> str:
    profs = client.get("/api/profiles").json()
    assert profs, "instalação nova deve criar o perfil inicial"
    return profs[0]["id"]


@pytest.fixture
def H(pid):
    """Headers com o perfil ativo."""
    return {"X-Profile": pid}
