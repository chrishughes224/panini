from __future__ import annotations

import json

import asyncpg
import httpx


async def _tap(client: httpx.AsyncClient, code: str, times: int) -> None:
    for _ in range(times):
        await client.post(f"/checklist/toggle/{code}", data={"edit_mode": "false"})


async def _quantity(pool: asyncpg.Pool, code: str) -> int:
    value = await pool.fetchval(
        """
        select ce.quantity from collection_entries ce
        join stickers s on s.id = ce.sticker_id where s.code = $1
        """,
        code,
    )
    return int(value or 0)


async def test_duplicates_page_lists_only_spares(logged_in: httpx.AsyncClient) -> None:
    await _tap(logged_in, "MEX1", 2)  # a spare
    await _tap(logged_in, "BRA2", 1)  # owned, not spare

    page = await logged_in.get("/duplicates")

    assert page.status_code == 200
    assert "MEX1" in page.text
    assert "BRA2" not in page.text


async def test_tap_in_grid_trades_away_one_copy(
    logged_in: httpx.AsyncClient, pool: asyncpg.Pool
) -> None:
    await _tap(logged_in, "MEX1", 3)

    response = await logged_in.post("/duplicates/remove/MEX1")

    assert response.status_code == 200
    assert await _quantity(pool, "MEX1") == 2


async def test_trade_away_by_code_only_acts_on_genuine_duplicates(
    logged_in: httpx.AsyncClient, pool: asyncpg.Pool
) -> None:
    await _tap(logged_in, "MEX1", 2)  # duplicate
    await _tap(logged_in, "BRA2", 1)  # single copy - must be protected

    ok = await logged_in.post("/duplicates/trade-away", data={"code": " mex 1"})
    assert json.loads(ok.headers["hx-trigger"])["trade-away-result"] == {"ok": True, "code": "MEX1"}
    assert await _quantity(pool, "MEX1") == 1

    again = await logged_in.post("/duplicates/trade-away", data={"code": "MEX1"})
    assert json.loads(again.headers["hx-trigger"])["trade-away-result"]["reason"] == "no_spare"
    assert await _quantity(pool, "MEX1") == 1

    single = await logged_in.post("/duplicates/trade-away", data={"code": "BRA2"})
    assert json.loads(single.headers["hx-trigger"])["trade-away-result"]["reason"] == "no_spare"
    assert await _quantity(pool, "BRA2") == 1  # never touches a single-owned copy

    unknown = await logged_in.post("/duplicates/trade-away", data={"code": "nope"})
    assert json.loads(unknown.headers["hx-trigger"])["trade-away-result"]["reason"] == "unknown"


async def test_export_needs_and_swaps_render(logged_in: httpx.AsyncClient) -> None:
    await _tap(logged_in, "MEX1", 2)

    needs = await logged_in.get("/export/needs")
    swaps = await logged_in.get("/export/swaps")

    assert needs.status_code == 200 and "Needs" in needs.text
    assert swaps.status_code == 200 and "Swaps" in swaps.text
    assert "MEX" in swaps.text  # the spare appears on the swaps list


async def test_data_is_private_per_user(http: httpx.AsyncClient, pool: asyncpg.Pool) -> None:
    await http.post(
        "/register",
        data={"username": "alice", "email": "a@example.com", "password": "correct-horse-1"},
    )
    await _tap(http, "MEX1", 2)
    await http.post("/logout")

    await http.post(
        "/register",
        data={"username": "bob", "email": "b@example.com", "password": "correct-horse-1"},
    )
    page = await http.get("/duplicates")

    assert "MEX1" not in page.text  # bob must not see alice's spares
