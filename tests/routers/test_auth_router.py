from __future__ import annotations

import httpx

FORM = {"username": "alice", "email": "alice@example.com", "password": "correct-horse-1"}


async def test_protected_pages_require_login(http: httpx.AsyncClient) -> None:
    for path in ("/checklist", "/duplicates", "/export/needs", "/export/swaps"):
        assert (await http.get(path)).status_code == 401, path


async def test_root_redirects_by_login_state(http: httpx.AsyncClient) -> None:
    anon = await http.get("/")
    assert anon.status_code == 307 and anon.headers["location"] == "/login"

    await http.post("/register", data=FORM)
    authed = await http.get("/")
    assert authed.headers["location"] == "/checklist"


async def test_register_logs_in_and_sets_session_cookie(http: httpx.AsyncClient) -> None:
    response = await http.post("/register", data=FORM)

    assert response.status_code == 303
    assert response.headers["location"] == "/checklist"
    set_cookie = response.headers["set-cookie"].lower()
    assert "panini_session=" in set_cookie and "httponly" in set_cookie
    assert (await http.get("/checklist")).status_code == 200


async def test_register_validation_and_conflict_messages(http: httpx.AsyncClient) -> None:
    short = await http.post("/register", data={**FORM, "password": "short"})
    assert short.status_code == 400

    await http.post("/register", data=FORM)
    http.cookies.clear()
    clash = await http.post("/register", data=FORM)
    assert clash.status_code == 409
    assert "already taken" in clash.text


async def test_login_success_and_failure(http: httpx.AsyncClient) -> None:
    await http.post("/register", data=FORM)
    http.cookies.clear()

    bad = await http.post("/login", data={"username": "alice", "password": "nope-nope-1"})
    assert bad.status_code == 401
    assert (await http.get("/checklist")).status_code == 401

    good = await http.post("/login", data={"username": "alice", "password": "correct-horse-1"})
    assert good.status_code == 303
    assert (await http.get("/checklist")).status_code == 200


async def test_logout_invalidates_the_session_server_side(http: httpx.AsyncClient) -> None:
    await http.post("/register", data=FORM)
    token = http.cookies["panini_session"]

    out = await http.post("/logout")
    assert out.status_code == 303 and out.headers["location"] == "/login"

    # Replaying the old cookie must fail: the session row is gone, not just the cookie.
    http.cookies.clear()
    http.cookies.set("panini_session", token)
    assert (await http.get("/checklist")).status_code == 401
