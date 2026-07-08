"""Build 'needs' and 'swaps' exports (plain-text and shareable-image data)
from a user's collection.

Pure view logic - takes the already-fetched, sort_order-ordered sticker list
(as returned by `collection_service.get_collection_for_user`) and has no
database or FastAPI dependency, so it can be unit tested with plain
in-memory fixtures, same as `checklist_view.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.sticker import StickerStatus, StickerWithStatus

_CODE_PATTERN = re.compile(r"^([A-Za-z]+)(\d+)$")

# ISO 3166-1 alpha-2 codes (or a GB subdivision code for the home nations,
# which have no ISO country code of their own) for each of the 48 team
# prefixes. Used both to derive the flag emoji shown in the plain-text list
# and as the flagcdn.com lookup code for the shareable image.
_TEAM_ISO_CODES: dict[str, str] = {
    "MEX": "MX", "RSA": "ZA", "KOR": "KR", "CZE": "CZ",
    "CAN": "CA", "BIH": "BA", "QAT": "QA", "SUI": "CH",
    "BRA": "BR", "MAR": "MA", "HAI": "HT", "SCO": "GB-SCT",
    "USA": "US", "PAR": "PY", "AUS": "AU", "TUR": "TR",
    "GER": "DE", "CUW": "CW", "CIV": "CI", "ECU": "EC",
    "NED": "NL", "JPN": "JP", "SWE": "SE", "TUN": "TN",
    "BEL": "BE", "EGY": "EG", "IRN": "IR", "NZL": "NZ",
    "ESP": "ES", "CPV": "CV", "KSA": "SA", "URU": "UY",
    "FRA": "FR", "SEN": "SN", "IRQ": "IQ", "NOR": "NO",
    "ARG": "AR", "ALG": "DZ", "AUT": "AT", "JOR": "JO",
    "POR": "PT", "COD": "CD", "UZB": "UZ", "COL": "CO",
    "ENG": "GB-ENG", "CRO": "HR", "GHA": "GH", "PAN": "PA",
}

# England and Scotland aren't ISO countries, so their flags are Unicode
# "tag sequence" subdivision flags rather than the usual two-letter
# regional-indicator pairs - spelled out literally rather than derived.
_SUBDIVISION_FLAGS: dict[str, str] = {
    "GB-SCT": "\U0001f3f4\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f",
    "GB-ENG": "\U0001f3f4\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f",
}


def _flag_emoji(iso_code: str) -> str:
    """Convert an ISO alpha-2 code to its flag emoji (regional indicators)."""
    if iso_code in _SUBDIVISION_FLAGS:
        return _SUBDIVISION_FLAGS[iso_code]
    return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in iso_code)


def _condense_ranges(numbers: list[int]) -> str:
    """Render sorted numbers as "1-5, 7, 9-12", condensing runs of 2+."""
    parts: list[str] = []
    start = prev = numbers[0]
    for n in numbers[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(f"{start}-{prev}" if prev > start else str(start))
        start = prev = n
    parts.append(f"{start}-{prev}" if prev > start else str(start))
    return ", ".join(parts)


def _group_by_prefix(items: list[StickerWithStatus]) -> tuple[list[str], dict[str, list[int]]]:
    """Split sticker codes into bare codes (no numeric suffix) and
    prefix -> numbers groups, in first-seen order (matches catalogue order
    since `items` is sort_order-ordered already)."""
    groups: dict[str, list[int]] = {}
    bare: list[str] = []
    for item in items:
        code = item.sticker.code
        match = _CODE_PATTERN.match(code)
        if match is None:
            bare.append(code)
            continue
        prefix, number = match.group(1), int(match.group(2))
        groups.setdefault(prefix, []).append(number)
    return bare, groups


def _group_lines(items: list[StickerWithStatus]) -> str:
    """Render sticker codes as one line per prefix, e.g. "FWC: 1, 3, 7".

    A code with no numeric suffix (the standalone "00") is rendered as a
    bare line instead. Team prefixes are preceded by that nation's flag
    emoji. Numbers are listed individually here (not range-condensed) -
    that condensing is only applied in the shareable image; see
    `_build_team_rows`.
    """
    bare, groups = _group_by_prefix(items)
    lines = [*bare]
    for prefix, numbers in groups.items():
        iso_code = _TEAM_ISO_CODES.get(prefix)
        label = f"{_flag_emoji(iso_code)} {prefix}" if iso_code else prefix
        lines.append(f"{label}: {', '.join(str(n) for n in sorted(numbers))}")
    return "\n".join(lines)


def build_needs_list(stickers: list[StickerWithStatus]) -> str:
    """Plain-text list of stickers not yet owned, grouped by prefix."""
    needed = [item for item in stickers if item.status == StickerStatus.NOT_OWNED]
    return _group_lines(needed)


def build_swaps_list(stickers: list[StickerWithStatus]) -> str:
    """Plain-text list of duplicate-owned stickers, grouped by prefix."""
    spares = [item for item in stickers if item.status == StickerStatus.DUPLICATE]
    return _group_lines(spares)


@dataclass(frozen=True, slots=True)
class TeamExportRow:
    """One nation's row for the shareable image (flag-card grid)."""

    code: str
    iso_code: str
    numbers: str


def _build_team_rows(items: list[StickerWithStatus]) -> list[TeamExportRow]:
    """Team-only rows (with flagcdn.com lookup codes), for the shareable
    image. Non-team stickers ("00", FWC, CC) have no national flag, so
    they're omitted here - they still appear in the plain-text list."""
    _bare, groups = _group_by_prefix(items)
    return [
        TeamExportRow(
            code=prefix,
            iso_code=_TEAM_ISO_CODES[prefix].lower(),
            numbers=_condense_ranges(sorted(numbers)),
        )
        for prefix, numbers in groups.items()
        if prefix in _TEAM_ISO_CODES
    ]


def build_needs_rows(stickers: list[StickerWithStatus]) -> list[TeamExportRow]:
    """Team rows for stickers not yet owned, for the shareable image."""
    needed = [item for item in stickers if item.status == StickerStatus.NOT_OWNED]
    return _build_team_rows(needed)


def build_swaps_rows(stickers: list[StickerWithStatus]) -> list[TeamExportRow]:
    """Team rows for duplicate-owned stickers, for the shareable image."""
    spares = [item for item in stickers if item.status == StickerStatus.DUPLICATE]
    return _build_team_rows(spares)
