"""
Encolhe as capas ja cacheadas para o tamanho da grade (max. 300x450 JPEG).

As capas eram guardadas na resolucao completa da pagina extraida (~900 KB cada,
~1 GB no total). O servidor agora ja gera miniaturas; este script converte o
acervo antigo uma unica vez. E RETOMAVEL (arquivos ja pequenos sao pulados).

IMPORTANTE: as paginas de leitura (cache/covers/pages_*/) ficam intactas.

Uso:  python backend/shrink_covers.py
"""
import io
import os
import sys
from pathlib import Path

from PIL import Image

_ROOT = Path(os.getenv("OMNIVAULT_HOME") or Path(__file__).parent.parent)
DIRS = [_ROOT / "cache/covers", _ROOT / "cache/main_covers"]
SKIP_UNDER = 120 * 1024   # ja e miniatura


def shrink(path: Path) -> int:
    """Reencoda uma capa; devolve os bytes poupados (0 se pulou)."""
    size = path.stat().st_size
    if size <= SKIP_UNDER:
        return 0
    try:
        img = Image.open(path).convert("RGB")
        img.thumbnail((300, 450), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88, optimize=True)
        out = buf.getvalue()
        if len(out) >= size:
            return 0
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(out)
        tmp.replace(path)
        return size - len(out)
    except Exception as e:
        print(f"  [--] {path.name}: {e}")
        return 0


def main():
    total_saved = 0
    total_files = 0
    for d in DIRS:
        if not d.exists():
            continue
        files = [f for f in d.glob("*.jpg")]   # so o nivel de cima: pages_*/ intacto
        print(f"{d.name}: {len(files)} capas")
        for i, f in enumerate(files, 1):
            saved = shrink(f)
            total_saved += saved
            total_files += 1 if saved else 0
            if i % 100 == 0:
                print(f"  ... {i}/{len(files)} ({total_saved/1024/1024:.0f} MB poupados)")
    print(f"\n=== Fim === {total_files} capas encolhidas - {total_saved/1024/1024:.0f} MB poupados")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    main()
