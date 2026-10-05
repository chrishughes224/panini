"""Static definition of the confirmed sticker catalogue.

This module encodes the decisions locked in during planning (see
implementation1.md, Section 0): the 48 team codes grouped A-L, and the grid
ordering `00 -> FWC1-19 -> teams by group -> CC1-12`.

It is only consumed by `scripts/seed_catalogue.py` to populate the `Sticker`
table once. It is intentionally kept separate from `sticker_service.py`,
which only *reads* the catalogue back out of the database at request time.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.sticker import StickerKind

# Confirmed team codes, grouped A-L in official 2026 World Cup group order.
# Order within each group tuple is preserved in the seeded sort_order.
GROUPS: dict[str, tuple[str, str, str, str]] = {
    "A": ("MEX", "RSA", "KOR", "CZE"),
    "B": ("CAN", "BIH", "QAT", "SUI"),
    "C": ("BRA", "MAR", "HAI", "SCO"),
    "D": ("USA", "PAR", "AUS", "TUR"),
    "E": ("GER", "CUW", "CIV", "ECU"),
    "F": ("NED", "JPN", "SWE", "TUN"),
    "G": ("BEL", "EGY", "IRN", "NZL"),
    "H": ("ESP", "CPV", "KSA", "URU"),
    "I": ("FRA", "SEN", "IRQ", "NOR"),
    "J": ("ARG", "ALG", "AUT", "JOR"),
    "K": ("POR", "COD", "UZB", "COL"),
    "L": ("ENG", "CRO", "GHA", "PAN"),
}

STICKERS_PER_TEAM = 20
FWC_COUNT = 19
CC_COUNT = 12

# Reverse of GROUPS, e.g. {"MEX": "A", "RSA": "A", ..., "PAN": "L"}
TEAM_TO_GROUP: dict[str, str] = {
    team_code: group_letter
    for group_letter, team_codes in GROUPS.items()
    for team_code in team_codes
}

# ISO 3166-1 alpha-2 codes (or a GB subdivision code for the home nations,
# which have no ISO country code of their own) for each of the 48 team
# prefixes - used for flag lookups (flagcdn.com images, emoji derivation).
TEAM_ISO_CODES: dict[str, str] = {
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

# Full display names for each of the 48 team prefixes.
TEAM_NAMES: dict[str, str] = {
    "MEX": "Mexico", "RSA": "South Africa", "KOR": "South Korea", "CZE": "Czech Republic",
    "CAN": "Canada", "BIH": "Bosnia & Herzegovina", "QAT": "Qatar", "SUI": "Switzerland",
    "BRA": "Brazil", "MAR": "Morocco", "HAI": "Haiti", "SCO": "Scotland",
    "USA": "United States", "PAR": "Paraguay", "AUS": "Australia", "TUR": "Turkey",
    "GER": "Germany", "CUW": "Curaçao", "CIV": "Ivory Coast", "ECU": "Ecuador",
    "NED": "Netherlands", "JPN": "Japan", "SWE": "Sweden", "TUN": "Tunisia",
    "BEL": "Belgium", "EGY": "Egypt", "IRN": "Iran", "NZL": "New Zealand",
    "ESP": "Spain", "CPV": "Cape Verde", "KSA": "Saudi Arabia", "URU": "Uruguay",
    "FRA": "France", "SEN": "Senegal", "IRQ": "Iraq", "NOR": "Norway",
    "ARG": "Argentina", "ALG": "Algeria", "AUT": "Austria", "JOR": "Jordan",
    "POR": "Portugal", "COD": "DR Congo", "UZB": "Uzbekistan", "COL": "Colombia",
    "ENG": "England", "CRO": "Croatia", "GHA": "Ghana", "PAN": "Panama",
}


@dataclass(frozen=True, slots=True)
class CatalogueRow:
    """One row to be inserted into the `Sticker` table."""

    code: str
    kind: StickerKind
    team_code: str | None
    sort_order: int


def build_catalogue() -> list[CatalogueRow]:
    """Build the full, ordered 992-sticker catalogue.

    Order: `00`, `FWC1`-`FWC19`, each group A-L (teams in group order, each
    team's 20 stickers sequential), then `CC1`-`CC12`.
    """
    rows: list[CatalogueRow] = []
    order = 0

    rows.append(CatalogueRow(code="00", kind=StickerKind.SPECIAL, team_code=None, sort_order=order))
    order += 1

    for n in range(1, FWC_COUNT + 1):
        rows.append(
            CatalogueRow(code=f"FWC{n}", kind=StickerKind.GENERIC, team_code=None, sort_order=order)
        )
        order += 1

    for group_letter in sorted(GROUPS):
        for team_code in GROUPS[group_letter]:
            for n in range(1, STICKERS_PER_TEAM + 1):
                rows.append(
                    CatalogueRow(
                        code=f"{team_code}{n}",
                        kind=StickerKind.TEAM,
                        team_code=team_code,
                        sort_order=order,
                    )
                )
                order += 1

    for n in range(1, CC_COUNT + 1):
        rows.append(
            CatalogueRow(code=f"CC{n}", kind=StickerKind.PROMO, team_code=None, sort_order=order)
        )
        order += 1

    return rows


def expected_total_stickers() -> int:
    return 1 + FWC_COUNT + (len(GROUPS) * 4 * STICKERS_PER_TEAM) + CC_COUNT
