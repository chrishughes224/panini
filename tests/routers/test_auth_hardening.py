"""Hardening for an internet-facing app: invite-only sign-up, brute-force
limits, secure cookies and username-timing equalisation."""

from __future__ import annotations

import asyncpg
import httpx
import pytest

from app.config import Settings
from app.services import auth_service
from tests.conftest import INVITE_CODE


def _form(username: str = "alice", code: str = INVITE_CODE) -> dict[str, str]:
    return {
        "username": username,
        "email": f"{username}@example.com",
        "password": "correct-horse-1",
        "invite_code": code,
    }


async def _users(pool: asyncpg.Pool) -> int:
    return int(await pool.fetchval("select count(*) from users"))


async def _failed_login(http: httpx.AsyncClient, username: str = "alice", ip: str | None = None) -> int:
    headers = {"x-forwarded-for": ip} if ip else {}
    response = await http.post(
        "/login", data={"username": username, "password": "wrong-password"}, headers=headers
    )
    return response.status_code


# --- invite-only registration --------------------------------------------------

async def test_registration_closed_when_no_code_configured(
    http: httpx.AsyncClient, settings: Settings, pool: asyncpg.Pool
) -> None:
    settings.registration_code = ""

    page = await http.get("/register")
    assert "currently closed" in page.text and "<form" not in page.text

    attempt = await http.post("/register", data=_form(code=""))
    assert attempt.status_code == 403
    # An empty code must never match an empty configured code.
    assert await _users(pool) == 0


async def test_login_page_only_offers_sign_up_when_open(
    http: httpx.AsyncClient, settings: Settings
) -> None:
    assert "Create an account" in (await http.get("/login")).text

    settings.registration_code = ""
    assert "Create an account" not in (await http.get("/login")).text


async def test_register_form_asks_for_an_invite_code(http: httpx.AsyncClient) -> None:
    page = await http.get("/register")

    assert 'name="invite_code"' in page.text


@pytest.mark.parametrize("bad_code", ["", "nope", "TEST-INVITE", "test-invite-extra"])
async def test_wrong_invite_code_creates_nothing(
    http: httpx.AsyncClient, pool: asyncpg.Pool, bad_code: str
) -> None:
    response = await http.post("/register", data=_form(code=bad_code))

    assert response.status_code == 403
    assert "invite code" in response.text
    assert await _users(pool) == 0
    assert "set-cookie" not in response.headers


async def test_correct_invite_code_registers_and_logs_in(
    http: httpx.AsyncClient, pool: asyncpg.Pool
) -> None:
    response = await http.post("/register", data=_form(code=f"  {INVITE_CODE}  "))  # trims spaces

    assert response.status_code == 303
    assert await _users(pool) == 1
    assert (await http.get("/checklist")).status_code == 200


async def test_wrong_code_never_reveals_whether_a_username_is_taken(
    http: httpx.AsyncClient,
) -> None:
    await http.post("/register", data=_form("alice"))
    http.cookies.clear()

    taken_wrong_code = await http.post("/register", data=_form("alice", code="nope"))
    fresh_wrong_code = await http.post("/register", data=_form("brandnew", code="nope"))

    assert taken_wrong_code.status_code == fresh_wrong_code.status_code == 403
    assert "already taken" not in taken_wrong_code.text


async def test_invite_code_guessing_is_rate_limited(
    http: httpx.AsyncClient, pool: asyncpg.Pool
) -> None:
    for _ in range(3):  # register_max_failures_per_ip in the test settings
        assert (await http.post("/register", data=_form(code="guess"))).status_code == 403

    # Even the right code is refused once the address is locked out.
    locked = await http.post("/register", data=_form(code=INVITE_CODE))

    assert locked.status_code == 429
    assert "retry-after" in locked.headers
    assert await _users(pool) == 0


# --- login rate limiting -------------------------------------------------------

async def test_login_locks_out_after_repeated_failures(http: httpx.AsyncClient) -> None:
    await http.post("/register", data=_form("alice"))
    http.cookies.clear()

    codes = [await _failed_login(http) for _ in range(3)]
    assert codes == [401, 401, 401]

    # The correct password is now refused too: the lockout is on the account.
    locked = await http.post("/login", data={"username": "alice", "password": "correct-horse-1"})
    assert locked.status_code == 429
    assert locked.headers["retry-after"] == str(15 * 60)
    assert "Too many" in locked.text
    assert (await http.get("/checklist")).status_code == 401


async def test_lockout_is_per_account_not_global(http: httpx.AsyncClient) -> None:
    await http.post("/register", data=_form("alice"))
    await http.post("/register", data=_form("bob"))
    http.cookies.clear()
    for _ in range(3):
        await _failed_login(http, "alice", ip="10.0.0.1")

    bob = await http.post(
        "/login",
        data={"username": "bob", "password": "correct-horse-1"},
        headers={"x-forwarded-for": "10.0.0.2"},
    )

    assert bob.status_code == 303


async def test_username_case_variants_share_one_counter(http: httpx.AsyncClient) -> None:
    await http.post("/register", data=_form("alice"))
    http.cookies.clear()

    for name in ("alice", "ALICE", "Alice"):
        await _failed_login(http, name, ip=f"10.0.1.{len(name)}")

    assert await _failed_login(http, "aLiCe", ip="10.0.9.9") == 429


async def test_successful_login_resets_the_failure_count(http: httpx.AsyncClient) -> None:
    await http.post("/register", data=_form("alice"))
    http.cookies.clear()

    await _failed_login(http)
    await _failed_login(http)
    ok = await http.post("/login", data={"username": "alice", "password": "correct-horse-1"})
    assert ok.status_code == 303
    http.cookies.clear()

    # Two more failures would have tipped a counter that was not reset (2 + 2 > 3).
    assert await _failed_login(http) == 401
    assert await _failed_login(http) == 401
    final = await http.post("/login", data={"username": "alice", "password": "correct-horse-1"})
    assert final.status_code == 303


async def test_spraying_many_usernames_from_one_address_is_blocked(
    http: httpx.AsyncClient,
) -> None:
    for i in range(5):  # login_max_failures_per_ip in the test settings
        await _failed_login(http, f"victim{i}", ip="203.0.113.7")

    blocked = await _failed_login(http, "victim99", ip="203.0.113.7")
    elsewhere = await _failed_login(http, "victim99", ip="203.0.113.8")

    assert blocked == 429
    assert elsewhere == 401


async def test_forwarded_for_is_ignored_unless_trusted(
    http: httpx.AsyncClient, settings: Settings
) -> None:
    """Without TRUST_FORWARDED_FOR a client cannot dodge the per-address limit
    just by sending a different X-Forwarded-For on every request."""
    settings.trust_forwarded_for = False

    for i in range(5):
        await _failed_login(http, f"victim{i}", ip=f"198.51.100.{i}")

    assert await _failed_login(http, "victim99", ip="198.51.100.200") == 429


async def test_unknown_user_still_does_a_password_hash_check(
    http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Timing: a nonexistent username must cost the same hashing work."""
    calls: list[str] = []
    real = auth_service.verify_password

    def spy(plain: str, hashed: str) -> bool:
        calls.append(hashed)
        return real(plain, hashed)

    monkeypatch.setattr(auth_service, "verify_password", spy)

    response = await http.post("/login", data={"username": "ghost", "password": "whatever-1"})

    assert response.status_code == 401
    assert len(calls) == 1 and calls[0].startswith("$argon2")


# --- session cookie --------------------------------------------------------------

async def test_session_cookie_is_secure_httponly_samesite(http: httpx.AsyncClient) -> None:
    registered = await http.post("/register", data=_form())
    cookie = registered.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie

    http.cookies.clear()
    login = await http.post("/login", data={"username": "alice", "password": "correct-horse-1"})
    cookie = login.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie


async def test_cookie_secure_can_be_disabled_for_plain_http_dev(
    http: httpx.AsyncClient, settings: Settings
) -> None:
    settings.cookie_secure = False

    response = await http.post("/register", data=_form())

    cookie_attrs = [part.strip() for part in response.headers["set-cookie"].lower().split(";")]
    assert "secure" not in cookie_attrs


async def test_secure_is_on_by_default() -> None:
    assert Settings(_env_file=None).cookie_secure is True
    assert Settings(_env_file=None).registration_code == ""
