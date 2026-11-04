"""Testes básicos (read-only) — não escrevem em data/ nem cache/."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import extractor
import reading_manager
import local_client


def test_is_image():
    assert extractor._is_image("page.jpg")
    assert extractor._is_image("PAGE.PNG")
    assert not extractor._is_image("readme.txt")


def test_sorted_images_skips_macosx_and_nonimages():
    names = ["__MACOSX/x.jpg", "b.jpg", "a.png", "notes.txt"]
    assert extractor._sorted_images(names) == ["a.png", "b.jpg"]


def test_local_id_roundtrip_is_deterministic():
    a = local_client.path_to_id(r"C:\Comics\Spider-Man's Tale.cbz")
    b = local_client.path_to_id(r"C:\Comics\Spider-Man's Tale.cbz")
    assert a == b and a.startswith("local_")
    assert local_client.is_local(a)


def test_stats_has_expected_keys():
    # perfil inexistente → estado vazio (só lê; não cria nada em data/)
    s = reading_manager.get_stats("perfilteste")
    for k in ("total_read", "total_in_progress", "total_queue",
              "read_this_week", "read_this_month", "recent"):
        assert k in s
