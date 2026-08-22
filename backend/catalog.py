"""
catalog.py — the contractor's property catalog (data + generated artwork).

DealBench is now dressed as a real contractor's storefront: **Cornerstone Homes**,
a fictional builder in the town of Marlowe Ridge. Each listing carries the full
public detail a buyer would expect (address, beds/baths, sqft, year, lot, HOA,
features, a photo) plus its **public asking price**.

Each listing ALSO carries a hidden ``floor_price`` — the lowest the contractor
would accept. That number is the seller's reservation price for the negotiation
engine and is *never* exposed in any public payload. `public()` strips it out;
the session layer reads it directly for the deterministic engine. This mirrors
the whole DealBench principle: the buyer's UI only ever knows *public* numbers,
so the convergence is honest by construction.

Photos are generated as flat-illustration SVGs (base64 data URIs) so the whole
site is self-contained and works offline — no external image hosts.
"""
from __future__ import annotations

import base64
from urllib.parse import quote  # noqa: F401  (kept for callers who prefer utf8 URIs)


# ---------------------------------------------------------------------------
# Artwork: a small parametric flat-illustration of a house + yard.
# ---------------------------------------------------------------------------
def _house_svg(pal: dict, *, windows: int = 4, garage: bool = True,
               storeys: int = 2) -> str:
    """Return an SVG string for a stylised house scene tinted by ``pal``."""
    sky_top, sky_bot = pal["sky_top"], pal["sky_bot"]
    sun, hill, ground = pal["sun"], pal["hill"], pal["ground"]
    wall, roof, door, glass = pal["wall"], pal["roof"], pal["door"], pal["glass"]
    trim = pal.get("trim", "#ffffff")
    sun_x = pal.get("sun_x", 660)

    # Window grid on the facade.
    win = []
    cols = 3 if windows >= 5 else 2
    xs = [300, 470] if cols == 2 else [292, 402, 512]
    ys = [292] if storeys == 1 else [270, 356]
    placed = 0
    for y in ys:
        for x in xs:
            if placed >= windows:
                break
            win.append(
                f"<rect x='{x}' y='{y}' width='52' height='46' rx='4' fill='{glass}' "
                f"stroke='{trim}' stroke-width='4'/>"
                f"<line x1='{x+26}' y1='{y}' x2='{x+26}' y2='{y+46}' stroke='{trim}' stroke-width='3'/>"
                f"<line x1='{x}' y1='{y+23}' x2='{x+52}' y2='{y+23}' stroke='{trim}' stroke-width='3'/>"
            )
            placed += 1
    windows_svg = "".join(win)

    garage_svg = ""
    if garage:
        garage_svg = (
            f"<rect x='568' y='330' width='120' height='96' rx='6' fill='{wall}' "
            f"stroke='{trim}' stroke-width='4'/>"
            f"<rect x='582' y='346' width='92' height='80' rx='4' fill='{glass}' opacity='0.8'/>"
            f"<line x1='582' y1='372' x2='674' y2='372' stroke='{trim}' stroke-width='3'/>"
            f"<line x1='582' y1='398' x2='674' y2='398' stroke='{trim}' stroke-width='3'/>"
        )

    roof_y = 250 if storeys == 2 else 300
    wall_y = roof_y
    svg = f"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 800 500' preserveAspectRatio='xMidYMid slice'>
<defs>
 <linearGradient id='sky' x1='0' y1='0' x2='0' y2='1'>
  <stop offset='0' stop-color='{sky_top}'/><stop offset='1' stop-color='{sky_bot}'/>
 </linearGradient>
</defs>
<rect width='800' height='500' fill='url(#sky)'/>
<circle cx='{sun_x}' cy='108' r='48' fill='{sun}' opacity='0.9'/>
<path d='M0 372 Q 210 300 420 358 T 800 344 V500 H0 Z' fill='{hill}' opacity='0.55'/>
<rect y='398' width='800' height='102' fill='{ground}'/>
<g>
 <rect x='96' y='300' width='16' height='104' fill='#7c5a3a'/>
 <circle cx='104' cy='286' r='46' fill='{hill}'/>
 <circle cx='140' cy='300' r='34' fill='{hill}' opacity='0.85'/>
</g>
<rect x='250' y='{wall_y}' width='300' height='{420-wall_y}' fill='{wall}'/>
<polygon points='224,{roof_y} 400,{roof_y-104} 576,{roof_y}' fill='{roof}'/>
<rect x='250' y='{wall_y}' width='300' height='14' fill='{roof}' opacity='0.85'/>
{windows_svg}
<rect x='372' y='342' width='56' height='78' rx='4' fill='{door}' stroke='{trim}' stroke-width='4'/>
<circle cx='418' cy='384' r='4' fill='{trim}'/>
{garage_svg}
<rect x='250' y='416' width='300' height='6' fill='{roof}' opacity='0.4'/>
</svg>"""
    return svg


def _data_uri(svg: str) -> str:
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


# ---------------------------------------------------------------------------
# Palettes — one per listing so the gallery reads as distinct homes.
# ---------------------------------------------------------------------------
_PALETTES = {
    "dawn":    {"sky_top": "#fde9d3", "sky_bot": "#f7c59f", "sun": "#ffd58a", "hill": "#e3a977",
                "ground": "#ccb48b", "wall": "#f4efe6", "roof": "#8a5a44", "door": "#3f5e63",
                "glass": "#bfe0e6", "trim": "#ffffff", "sun_x": 640, "accent": "#C97B5A"},
    "sage":    {"sky_top": "#e7f0e6", "sky_bot": "#c7ddc9", "sun": "#f4efb1", "hill": "#8fae8b",
                "ground": "#a9c19b", "wall": "#eef2ec", "roof": "#5c7a63", "door": "#7d4f3a",
                "glass": "#cfe6de", "trim": "#ffffff", "sun_x": 150, "accent": "#5C8A6E"},
    "coast":   {"sky_top": "#dff1f7", "sky_bot": "#a9d7e6", "sun": "#fff2c4", "hill": "#7fb7c9",
                "ground": "#bcae8f", "wall": "#f6f8f8", "roof": "#3d6b82", "door": "#c56a4b",
                "glass": "#c9eaf2", "trim": "#ffffff", "sun_x": 660, "accent": "#3D8FA8"},
    "colonial":{"sky_top": "#eef1f6", "sky_bot": "#cdd7e6", "sun": "#f6efce", "hill": "#9aa7bd",
                "ground": "#b6b19a", "wall": "#eceff4", "roof": "#4a4f63", "door": "#6d2f34",
                "glass": "#ccd6e6", "trim": "#ffffff", "sun_x": 620, "accent": "#5A6478"},
    "urban":   {"sky_top": "#f0ecf6", "sky_bot": "#d8cfe6", "sun": "#f4e6c0", "hill": "#a596bd",
                "ground": "#b3a9bd", "wall": "#efe9f2", "roof": "#5b4a72", "door": "#c07a3a",
                "glass": "#ddd0ea", "trim": "#ffffff", "sun_x": 160, "accent": "#7D5CA8"},
    "craft":   {"sky_top": "#fdf1df", "sky_bot": "#f3d7ad", "sun": "#ffd98a", "hill": "#c79a6a",
                "ground": "#c2a878", "wall": "#f0e7d8", "roof": "#7a4a34", "door": "#3e5a4a",
                "glass": "#d8e6d2", "trim": "#ffffff", "sun_x": 640, "accent": "#B07A3C"},
    "estate":  {"sky_top": "#e9edf4", "sky_bot": "#c4cfe0", "sun": "#f7efcf", "hill": "#8f9db8",
                "ground": "#b0b394", "wall": "#f4f2ea", "roof": "#3c4358", "door": "#5d4a3a",
                "glass": "#cdd8ea", "trim": "#ffffff", "sun_x": 660, "accent": "#43507A"},
}


# ---------------------------------------------------------------------------
# The listings.  `floor_price` is the SELLER's private reservation — never
# serialised publicly.  ZOPA (floor <= asking) always holds; a buyer whose
# budget reaches the asking price can always find a deal.
# ---------------------------------------------------------------------------
_RAW: list[dict] = [
    {
        "id": "maple-court-42", "palette": "dawn",
        "address": "42 Maple Court", "neighborhood": "Marlowe Ridge",
        "type": "Modern Farmhouse", "beds": 4, "baths": 3, "sqft": 2450,
        "year_built": 2019, "lot_sqft": 8300, "garage": 2, "hoa_month": 0,
        "days_on_market": 21, "asking_price": 625000, "floor_price": 561000,
        "windows": 4, "storeys": 2,
        "tagline": "Vaulted ceilings, black-framed windows, and a chef's kitchen.",
        "description": (
            "A crisp modern farmhouse on a quiet cul-de-sac. Open-concept main "
            "floor with a 10-foot island, walk-in pantry, and a covered rear "
            "porch overlooking a level, fully fenced yard. Primary suite down, "
            "three beds up."),
        "features": ["Chef's kitchen", "Covered porch", "Fenced yard",
                     "Primary on main", "Tankless water heater"],
    },
    {
        "id": "birchwood-18", "palette": "sage",
        "address": "18 Birchwood Lane", "neighborhood": "Old Marlowe",
        "type": "Craftsman Bungalow", "beds": 3, "baths": 2, "sqft": 1780,
        "year_built": 2015, "lot_sqft": 6100, "garage": 1, "hoa_month": 0,
        "days_on_market": 44, "asking_price": 438000, "floor_price": 401000,
        "windows": 3, "storeys": 1,
        "tagline": "Single-level living with real hardwood throughout.",
        "description": (
            "A warm craftsman bungalow with tapered columns, a deep front porch, "
            "and site-finished oak floors. Updated bath, gas range, and a "
            "detached studio at the back of the lot — ideal as an office."),
        "features": ["Hardwood floors", "Front porch", "Detached studio",
                     "Gas range", "New roof (2022)"],
    },
    {
        "id": "harbor-view-7", "palette": "coast",
        "address": "7 Harbor View Terrace", "neighborhood": "The Point",
        "type": "Waterfront Contemporary", "beds": 5, "baths": 4, "sqft": 3620,
        "year_built": 2021, "lot_sqft": 11200, "garage": 3, "hoa_month": 120,
        "days_on_market": 12, "asking_price": 915000, "floor_price": 846000,
        "windows": 6, "storeys": 2,
        "tagline": "Walls of glass and a dock slip on the inlet.",
        "description": (
            "Dramatic contemporary on the water with floor-to-ceiling glazing, a "
            "floating staircase, and an owner's wing with a spa bath. Deeded dock "
            "slip, three-car garage, and a screened lanai for the summer."),
        "features": ["Water frontage", "Deeded dock slip", "3-car garage",
                     "Screened lanai", "Spa bath"],
    },
    {
        "id": "old-mill-231", "palette": "colonial",
        "address": "231 Old Mill Road", "neighborhood": "Millbrook",
        "type": "Colonial (renovated)", "beds": 3, "baths": 3, "sqft": 2100,
        "year_built": 1998, "lot_sqft": 9400, "garage": 2, "hoa_month": 0,
        "days_on_market": 63, "asking_price": 489000, "floor_price": 447000,
        "windows": 4, "storeys": 2,
        "tagline": "Classic center-hall colonial, fully renovated in 2020.",
        "description": (
            "A dignified center-hall colonial taken back to the studs in 2020: "
            "new kitchen, baths, windows, and mechanicals. Formal living and "
            "dining, a family room with a wood stove, and a private, wooded lot."),
        "features": ["Renovated 2020", "Wood stove", "Wooded lot",
                     "New windows", "Finished basement"],
    },
    {
        "id": "sycamore-96", "palette": "urban",
        "address": "96 Sycamore Street, Unit B", "neighborhood": "Downtown Marlowe",
        "type": "Townhome", "beds": 2, "baths": 2, "sqft": 1320,
        "year_built": 2022, "lot_sqft": 0, "garage": 1, "hoa_month": 210,
        "days_on_market": 8, "asking_price": 362000, "floor_price": 335000,
        "windows": 3, "storeys": 2,
        "tagline": "Turn-key townhome two blocks from the market square.",
        "description": (
            "A nearly-new townhome steps from cafes and the Saturday market. "
            "Quartz counters, luxury vinyl plank, a tandem garage, and a private "
            "roof deck with skyline views. Low-maintenance, lock-and-leave living."),
        "features": ["Roof deck", "Quartz counters", "Tandem garage",
                     "Walk to market", "Smart thermostat"],
    },
    {
        "id": "aspen-grove-14", "palette": "craft",
        "address": "14 Aspen Grove", "neighborhood": "Marlowe Ridge",
        "type": "Craftsman", "beds": 4, "baths": 4, "sqft": 2980,
        "year_built": 2020, "lot_sqft": 9900, "garage": 2, "hoa_month": 45,
        "days_on_market": 30, "asking_price": 735000, "floor_price": 676000,
        "windows": 5, "storeys": 2,
        "tagline": "Coffered ceilings, a mudroom drop-zone, and a home office.",
        "description": (
            "A generous craftsman with a main-floor office, coffered great-room "
            "ceiling, and an oversized island. Upstairs: four beds including a "
            "junior suite, plus a laundry room that actually fits a folding table."),
        "features": ["Main-floor office", "Junior suite", "Mudroom",
                     "Coffered ceilings", "Oversized island"],
    },
    {
        "id": "lakeshore-305", "palette": "estate",
        "address": "305 Lakeshore Drive", "neighborhood": "Lakeshore Estates",
        "type": "Luxury Estate", "beds": 6, "baths": 5, "sqft": 4550,
        "year_built": 2023, "lot_sqft": 21800, "garage": 4, "hoa_month": 300,
        "days_on_market": 5, "asking_price": 1245000, "floor_price": 1151000,
        "windows": 6, "storeys": 2,
        "tagline": "New-construction estate on half an acre with a pool.",
        "description": (
            "A statement new-build on a half-acre: two-storey foyer, catering "
            "kitchen, glass wine room, and a primary retreat with dual closets. "
            "Resort backyard with a gunite pool, spa, and an outdoor kitchen."),
        "features": ["Gunite pool & spa", "Catering kitchen", "Wine room",
                     "4-car garage", "Half-acre lot"],
    },
]


def _compute(p: dict) -> dict:
    """Attach derived, public fields (photo, price/sqft) once at import."""
    pal = _PALETTES[p["palette"]]
    photo = _data_uri(_house_svg(pal, windows=p["windows"], garage=p["garage"] > 0,
                                 storeys=p["storeys"]))
    ppsf = round(p["asking_price"] / p["sqft"]) if p["sqft"] else None
    out = dict(p)
    out["accent"] = pal["accent"]
    out["photo"] = photo
    out["price_per_sqft"] = ppsf
    return out


# Fully-computed listings (internal — still contains floor_price).
PROPERTIES: list[dict] = [_compute(p) for p in _RAW]
_BY_ID: dict[str, dict] = {p["id"]: p for p in PROPERTIES}

# Fields that must NEVER leave the server.
_PRIVATE_FIELDS = ("floor_price", "palette")


def public(p: dict) -> dict:
    """A listing safe for any client payload — the private floor is stripped."""
    return {k: v for k, v in p.items() if k not in _PRIVATE_FIELDS}


def all_public() -> list[dict]:
    return [public(p) for p in PROPERTIES]


def get(pid: str) -> dict | None:
    """Internal accessor — includes the private floor_price."""
    return _BY_ID.get(pid)


def get_public(pid: str) -> dict | None:
    p = _BY_ID.get(pid)
    return public(p) if p else None
