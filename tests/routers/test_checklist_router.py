from __future__ import annotations

import json
import re

import asyncpg
import httpx

from app.services.catalogue_data import GROUPS


def _trigger(response: httpx.Response) -> dict[str, dict[str, object]]:
    parsed: dict[str, dict[str, object]] = json.loads(response.headers["hx-trigger"])
    return parsed


async def _quantity(pool: asyncpg.Pool, code: str) -> int:
    value = await pool.fetchval(
        """
        select ce.quantity from collection_entries ce
        join stickers s on s.id = ce.sticker_id where s.code = $1
        """,
        code,
    )
    return int(value or 0)


async def test_checklist_page_renders_full_catalogue(logged_in: httpx.AsyncClient) -> None:
    page = await logged_in.get("/checklist")

    assert page.status_code == 200
    assert "/ 992" in page.text
    assert 'id="sticker-MEX1"' in page.text and 'id="sticker-CC12"' in page.text
    for heatmap_id in ("heatmap-special", "heatmap-teams", "heatmap-promo"):
        assert f'id="{heatmap_id}"' in page.text
    assert page.text.count('class="group-card') == 12


async def test_tap_adds_then_makes_duplicate(
    logged_in: httpx.AsyncClient, pool: asyncpg.Pool
) -> None:
    first = await logged_in.post("/checklist/toggle/MEX1", data={"edit_mode": "false"})
    assert first.status_code == 200
    assert "is-owned" in first.text and "is-duplicate" not in first.text
    assert first.headers["hx-trigger"] == "sticker-updated"

    second = await logged_in.post("/checklist/toggle/MEX1", data={"edit_mode": "false"})
    assert "is-duplicate" in second.text
    assert await _quantity(pool, "MEX1") == 2


async def test_tap_refreshes_summary_heatmap_and_team_tile_out_of_band(
    logged_in: httpx.AsyncClient,
) -> None:
    response = await logged_in.post("/checklist/toggle/MEX1", data={"edit_mode": "false"})

    assert 'id="summary-bar" hx-swap-oob="true"' in response.text
    assert 'id="heatmap-teams" hx-swap-oob="true"' in response.text
    assert 'id="team-progress-MEX"' in response.text
    assert "1/20" in response.text  # the refreshed MEX tile


async def test_edit_mode_tap_undoes(logged_in: httpx.AsyncClient, pool: asyncpg.Pool) -> None:
    await logged_in.post("/checklist/toggle/MEX1", data={"edit_mode": "false"})
    await logged_in.post("/checklist/toggle/MEX1", data={"edit_mode": "false"})

    await logged_in.post("/checklist/toggle/MEX1", data={"edit_mode": "true"})
    assert await _quantity(pool, "MEX1") == 1
    await logged_in.post("/checklist/toggle/MEX1", data={"edit_mode": "true"})
    assert await _quantity(pool, "MEX1") == 0


async def test_quick_add_is_lenient_about_spacing_and_case(
    logged_in: httpx.AsyncClient, pool: asyncpg.Pool
) -> None:
    first = await logged_in.post("/checklist/quick-add", data={"code": " mex 6 "})
    result = _trigger(first)["quick-add-result"]
    assert result["ok"] is True and result["code"] == "MEX6" and result["status"] == "owned"

    second = await logged_in.post("/checklist/quick-add", data={"code": "MEX6"})
    assert _trigger(second)["quick-add-result"]["status"] == "duplicate"
    assert await _quantity(pool, "MEX6") == 2


async def test_quick_add_unknown_code_changes_nothing(
    logged_in: httpx.AsyncClient, pool: asyncpg.Pool
) -> None:
    response = await logged_in.post("/checklist/quick-add", data={"code": "zzz 99"})

    assert _trigger(response)["quick-add-result"] == {"ok": False, "code": "ZZZ99"}
    assert await pool.fetchval("select count(*) from collection_entries") == 0


async def test_check_reports_status_and_never_mutates(
    logged_in: httpx.AsyncClient, pool: asyncpg.Pool
) -> None:
    need = await logged_in.post("/checklist/check", data={"code": "mex 1"})
    assert _trigger(need)["check-result"] == {"ok": True, "code": "MEX1", "status": "not_owned"}

    await logged_in.post("/checklist/toggle/MEX1", data={"edit_mode": "false"})
    got = await logged_in.post("/checklist/check", data={"code": "MEX1"})
    assert _trigger(got)["check-result"]["status"] == "owned"

    unknown = await logged_in.post("/checklist/check", data={"code": "nope"})
    assert _trigger(unknown)["check-result"]["ok"] is False
    assert await _quantity(pool, "MEX1") == 1  # three checks, still exactly one copy


async def test_completed_group_flags_every_team_tile_complete(
    logged_in: httpx.AsyncClient, pool: asyncpg.Pool
) -> None:
    """Group A all-20/20 -> its four tiles carry data-complete="true", which
    is what turns the group card green; other groups stay incomplete."""
    teams_in_a = GROUPS["A"]
    user_id = await pool.fetchval("select id from users")
    await pool.execute(
        """
        insert into collection_entries (user_id, sticker_id, quantity)
        select $1, id, 1 from stickers where team_code = any($2::text[])
        """,
        user_id,
        list(teams_in_a),
    )

    page = await logged_in.get("/checklist")

    complete = set(re.findall(r'id="team-progress-([A-Z]+)"\s+data-complete="true"', page.text))
    assert complete == set(teams_in_a)
    incomplete = re.findall(r'id="team-progress-[A-Z]+"\s+data-complete="false"', page.text)
    assert len(incomplete) == 44  # the other 11 groups x 4 teams


# --- responsive layout (phones) ----------------------------------------------

async def test_page_has_no_fixed_minimum_width_that_forces_sideways_scroll(
    logged_in: httpx.AsyncClient,
) -> None:
    page = await logged_in.get("/checklist")

    assert "min-w-[750px]" not in page.text
    assert "overflow-x-auto" not in page.text.split('id="summary-bar"')[0].split("<main")[-1]


async def test_group_cards_are_two_columns_on_phones_and_scale_up(
    logged_in: httpx.AsyncClient,
) -> None:
    page = await logged_in.get("/checklist")

    # 2 x 6 on phones, 3 x 4 on tablets, 4 x 3 on desktop.
    assert "grid-cols-2 md:grid-cols-3 lg:grid-cols-4" in page.text


async def test_logged_in_pages_offer_a_hamburger_menu_with_every_destination(
    logged_in: httpx.AsyncClient,
) -> None:
    page = await logged_in.get("/checklist")
    menu = page.text.split('id="mobile-menu"')[1].split("</details>")[0]

    assert "md:hidden" in page.text.split('id="mobile-menu"')[1][:200]
    for expected in ('href="/checklist"', 'href="/duplicates"', 'hx-get="/export/needs"',
                     'hx-get="/export/swaps"', 'action="/logout"'):
        assert expected in menu


async def test_logged_out_pages_have_no_menu(http: httpx.AsyncClient) -> None:
    page = await http.get("/login")

    assert 'id="mobile-menu"' not in page.text


async def test_heatmap_layout_classes_survive_a_live_update_swap(
    logged_in: httpx.AsyncClient,
) -> None:
    """The tap response re-renders each heatmap out-of-band. Their grid
    placement classes must be inside that fragment, or the compact phone
    layout would break after the first tap."""
    page = await logged_in.get("/checklist")
    swap = await logged_in.post("/checklist/toggle/MEX1", data={"edit_mode": "false"})

    for heatmap_id, classes in (
        ("heatmap-teams", "col-start-1 row-start-1 row-span-2"),
        ("heatmap-special", "col-start-2 row-start-1"),
        ("heatmap-promo", "col-start-2 row-start-2"),
    ):
        initial = re.search(rf'<div id="{heatmap_id}"[^>]*class="([^"]*)"', page.text)
        swapped = re.search(rf'<div id="{heatmap_id}" hx-swap-oob="true"\s+class="([^"]*)"', swap.text)
        assert initial is not None and swapped is not None, heatmap_id
        assert initial.group(1) == swapped.group(1) == classes


async def test_heatmap_cells_use_whole_pixel_size_variable(logged_in: httpx.AsyncClient) -> None:
    page = await logged_in.get("/checklist")

    assert "repeat(20, var(--hm-cell, 7px))" in page.text
    assert "--hm-cell: 5px" in page.text  # phones; still a whole number of pixels
