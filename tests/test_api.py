"""Testes de ponta a ponta da API (FastAPI TestClient), numa instalação isolada
(OMNIVAULT_HOME temporário, ver conftest.py). Não usam rede nem Google Drive."""
import json
import pytest

JPEG = b"\xff\xd8"


# ── Instalação nova / perfis ──────────────────────────────────────────────────

def test_fresh_install_has_generic_profile(client):
    profs = client.get("/api/profiles").json()
    assert [p["name"] for p in profs] == ["Leitor"]


def test_profile_header_required(client):
    assert client.get("/api/reading/state").status_code == 409
    assert client.get("/api/reading/state", headers={"X-Profile": "naoexiste"}).status_code == 409


def test_profile_crud(client):
    p = client.post("/api/profiles", json={"name": "  Ana   Lima ", "avatar": "p3"}).json()
    assert p["name"] == "Ana Lima" and p["avatar"] == "p3"
    r = client.put(f"/api/profiles/{p['id']}", json={"name": "Ana"})
    assert r.status_code == 200 and r.json()["name"] == "Ana"
    assert client.post("/api/profiles", json={"name": "   ", "avatar": "p1"}).status_code in (400, 422)
    assert client.delete(f"/api/profiles/{p['id']}").status_code == 200
    assert all(x["id"] != p["id"] for x in client.get("/api/profiles").json())


def test_cannot_delete_last_profile(client, pid):
    assert len(client.get("/api/profiles").json()) == 1
    assert client.delete(f"/api/profiles/{pid}").status_code >= 400
    assert len(client.get("/api/profiles").json()) == 1


def test_profiles_are_isolated(client, H):
    other = client.post("/api/profiles", json={"name": "Outro", "avatar": "p2"}).json()
    client.post("/api/reading/queue", headers=H, json={"file_id": "x1", "name": "X.cbz"})
    st_other = client.get("/api/reading/state", headers={"X-Profile": other["id"]}).json()
    assert not st_other.get("queue")
    client.delete("/api/reading/queue/x1", headers=H)
    client.delete(f"/api/profiles/{other['id']}")


# ── Mesma origem (proteção contra sites de terceiros) ─────────────────────────

def test_cross_origin_request_is_blocked(client, H):
    r = client.post("/api/shutdown", headers={"Origin": "http://site-malicioso.example"})
    assert r.status_code == 403
    r = client.get("/api/local/browse", headers={"Origin": "http://site-malicioso.example"})
    assert r.status_code == 403


def test_same_origin_request_is_allowed(client, H):
    r = client.get("/api/reading/state", headers={**H, "Origin": "http://testserver"})
    assert r.status_code == 200


def test_no_cors_headers_by_default(client):
    r = client.get("/api/profiles", headers={"Origin": "http://testserver"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


# ── Biblioteca local: pastas, capas, páginas ──────────────────────────────────

@pytest.fixture(scope="module")
def comics(client, library):
    r = client.post("/api/config/folders/local", json={"name": "Teste", "path": str(library)})
    assert r.status_code == 200, r.text
    folders = client.get("/api/config/folders").json()
    assert any(f.get("local_path") == str(library) for f in folders)
    serie = library / "Série Teste"
    items = client.get("/api/local/items", params={"path": str(serie)}).json()
    return {c["name"]: c for c in items["comics"]}


def test_local_listing(comics):
    assert "Volume 01.cbz" in comics and "Volume 02.pdf" in comics
    assert all(c["id"].startswith("local_") for c in comics.values())


def test_invalid_local_folder_rejected(client, tmp_path):
    r = client.post("/api/config/folders/local", json={"name": "X", "path": str(tmp_path / "nao-existe")})
    assert r.status_code == 400


@pytest.mark.parametrize("name,pages", [("Volume 01.cbz", 3), ("Volume 02.pdf", 3), ("Volume 03.cb7", 2)])
def test_cover_info_and_pages(client, comics, name, pages):
    if name not in comics:
        pytest.skip("7-Zip não instalado: CB7 não testado")
    cid = comics[name]["id"]
    cover = client.get(f"/api/comics/{cid}/cover")
    assert cover.status_code == 200 and cover.content[:2] == JPEG
    info = client.get(f"/api/comics/{cid}/info").json()
    assert info["pages"] == pages
    assert client.get(f"/api/comics/{cid}/pages").json()["pages"] == pages
    for n in (0, pages - 1):
        pg = client.get(f"/api/comics/{cid}/page/{n}")
        assert pg.status_code == 200 and pg.content[:2] == JPEG


def _q(folder_path) -> str:
    """Como o front: encodeURIComponent do id (no Linux/macOS o id tem '/')."""
    from urllib.parse import quote
    return quote(str(folder_path), safe="")


def test_folder_cover(client, library):
    r = client.get(f"/api/folders/{_q(library / 'Série Teste')}/cover")
    assert r.status_code == 200 and r.content[:2] == JPEG
    assert client.post(f"/api/folders/{_q(library / 'Série Teste')}/cover/refresh").status_code == 200


def test_local_folder_in_list(client, library, H):
    """Pasta local numa lista: o id é um caminho (com '\' ou '/')."""
    lid = client.post("/api/lists", headers=H, json={"name": "Pastas"}).json()["id"]
    fid = str(library / "Série Teste")
    client.post(f"/api/lists/{lid}/comics", headers=H, json={"file_id": fid, "name": "Série Teste", "is_folder": True})
    assert any(c["id"] == fid for c in client.get("/api/lists", headers=H).json()[lid]["comics"])
    assert client.delete(f"/api/lists/{lid}/comics/{_q(fid)}", headers=H).status_code == 200
    assert not client.get("/api/lists", headers=H).json()[lid]["comics"]
    client.delete(f"/api/lists/{lid}", headers=H)


def test_local_search(client, library):
    r = client.get("/api/local/search", params={"path": str(library), "q": "volume 02"}).json()
    names = [c["name"] for c in r["results"]]
    assert "Volume 02.pdf" in names


# ── Estado de leitura ─────────────────────────────────────────────────────────

def test_progress_resume_and_finish(client, comics, H):
    cid = comics["Volume 01.cbz"]["id"]
    body = {"file_id": cid, "name": "Volume 01.cbz", "page": 2, "pages": 3}
    assert client.post("/api/reading/progress", headers=H, json=body).status_code == 200
    assert client.get(f"/api/comics/{cid}/info", headers=H).json()["saved_page"] == 2
    st = client.get("/api/reading/state", headers=H).json()
    assert st["in_progress"][cid]["page"] == 2
    assert sum(st.get("daily", {}).values()) >= 2        # heatmap contou as páginas
    client.post("/api/reading/finish", headers=H, json={"file_id": cid, "name": "Volume 01.cbz"})
    st = client.get("/api/reading/state", headers=H).json()
    assert cid in st["read"] and cid not in st["in_progress"]


def test_queue_rating_and_stats(client, comics, H):
    cid = comics["Volume 02.pdf"]["id"]
    client.post("/api/reading/queue", headers=H, json={"file_id": cid, "name": "Volume 02.pdf"})
    client.post("/api/reading/rate", headers=H, json={"file_id": cid, "name": "Volume 02.pdf", "stars": 4})
    st = client.get("/api/reading/state", headers=H).json()
    assert any(q["id"] == cid for q in st["queue"])
    assert st["ratings"][cid]["stars"] == 4
    client.post("/api/reading/rate", headers=H, json={"file_id": cid, "name": "Volume 02.pdf", "stars": 0})
    assert cid not in client.get("/api/reading/state", headers=H).json().get("ratings", {})
    stats = client.get("/api/stats", headers=H).json()
    assert stats["total_queue"] >= 1


def test_lists(client, comics, H):
    lst = client.post("/api/lists", headers=H, json={"name": "Favoritas"}).json()
    lid = lst.get("id") or next(k for k, v in client.get("/api/lists", headers=H).json().items()
                                if v["name"] == "Favoritas")
    cid = comics["Volume 02.pdf"]["id"]
    client.post(f"/api/lists/{lid}/comics", headers=H, json={"file_id": cid, "name": "Volume 02.pdf"})
    lists = client.get("/api/lists", headers=H).json()
    assert any(c["id"] == cid for c in lists[lid]["comics"])
    client.delete(f"/api/lists/{lid}/comics/{cid}", headers=H)
    client.delete(f"/api/lists/{lid}", headers=H)
    assert lid not in client.get("/api/lists", headers=H).json()


def test_finish_folder(client, library, comics, H):
    r = client.post("/api/reading/finish-folder", headers=H, params={"folder_id": str(library / "Série Teste")})
    assert r.status_code == 200 and r.json()["count"] == len(comics)


def test_backup_roundtrip(client, H):
    backup = client.get("/api/reading/state", headers=H).json()
    client.post("/api/reading/import", headers=H, json={"in_progress": {}, "read": {}, "queue": []})
    assert client.get("/api/reading/state", headers=H).json()["read"] == {}
    client.post("/api/reading/import", headers=H, json=backup)
    assert client.get("/api/reading/state", headers=H).json()["read"] == backup["read"]


# ── App / PWA ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/", "/reader.html", "/sw.js", "/manifest.json", "/profile.js"])
def test_static_shell(client, path):
    assert client.get(path).status_code == 200


def test_drive_without_credentials_shows_onboarding(client):
    assert client.get("/auth/status").json()["authenticated"] is False
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 200 and 'action="/auth/credentials"' in r.text


_DESKTOP = {"installed": {"client_id": "123-abc.apps.googleusercontent.com", "client_secret": "x",
                          "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                          "token_uri": "https://oauth2.googleapis.com/token",
                          "redirect_uris": ["http://localhost"]}}


def _send(client, payload: bytes):
    return client.post("/auth/credentials", files={"file": ("client_secret_1.json", payload, "application/json")},
                       follow_redirects=False)


def test_credentials_upload_only_from_this_pc(client):
    import drive_client
    r = _send(client, json.dumps(_DESKTOP).encode())  # TestClient não é 127.0.0.1
    assert r.status_code == 403 and not drive_client.CREDENTIALS_FILE.exists()


def test_credentials_upload_validates_and_saves(client, monkeypatch):
    import main, drive_client
    monkeypatch.setattr(main, "_is_local_client", lambda request: True)
    f = drive_client.CREDENTIALS_FILE
    try:
        r = _send(client, b"isto nao e json")
        assert r.status_code == 400 and "JSON" in r.text and not f.exists()
        r = _send(client, json.dumps({"web": _DESKTOP["installed"]}).encode())
        assert r.status_code == 400 and "Desktop" in r.text and not f.exists()
        r = _send(client, "﻿".encode("utf-8") + json.dumps(_DESKTOP).encode())  # com BOM também vale
        assert r.status_code == 303 and r.headers["location"] == "/auth/login"
        assert json.loads(f.read_text(encoding="utf-8")) == _DESKTOP
        r = client.get("/auth/login", follow_redirects=False)
        assert r.status_code in (302, 307) and r.headers["location"].startswith("https://accounts.google.com/")
        # credencial Web colocada à mão: o login explica em vez de mandar pro erro do Google
        f.write_text(json.dumps({"web": _DESKTOP["installed"]}), encoding="utf-8")
        r = client.get("/auth/login", follow_redirects=False)
        assert r.status_code == 200 and "Desktop" in r.text
    finally:
        f.unlink(missing_ok=True)
