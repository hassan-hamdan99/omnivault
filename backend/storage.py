"""Gravação atómica de ficheiros — evita corrupção quando há escritas
concorrentes (threads de pregen + pedidos). Escreve num temporário no mesmo
diretório e faz os.replace (atómico, inclusive no Windows)."""
import os
import tempfile
from pathlib import Path


def atomic_write(path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise
