"""District / area context from the ort catalog for LLM grounding."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, degrees, radians, sin, sqrt

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CatalogList
from app.schemas.domain import GeoBounds
from app.services.catalog_items import coerce_catalog_items
from app.services.catalog_store import ensure_catalog_defaults


@dataclass(frozen=True)
class DistrictContext:
    label: str
    description: str
    bounds: GeoBounds | None

    @property
    def center(self) -> tuple[float, float] | None:
        if self.bounds is None:
            return None
        lat = (self.bounds.south + self.bounds.north) / 2
        lng = (self.bounds.west + self.bounds.east) / 2
        return (lat, lng)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lng2 - lng1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def _extent_km(bounds: GeoBounds) -> tuple[float, float]:
    """Rough N–S and E–W extent in km at the rectangle center."""
    mid_lat = (bounds.south + bounds.north) / 2
    mid_lng = (bounds.west + bounds.east) / 2
    ns = _haversine_km(bounds.south, mid_lng, bounds.north, mid_lng)
    ew = _haversine_km(mid_lat, bounds.west, mid_lat, bounds.east)
    return ns, ew


def _cardinal(from_lat: float, from_lng: float, to_lat: float, to_lng: float) -> str:
    """Compass direction of `to` relative to `from` (Swedish)."""
    # Bearing from Centrum (from) toward district (to) — wait, we want district relative to centrum:
    # "ligger X km söder om Centrum" means district is south of centrum, so direction of district from centrum.
    d_lng = radians(to_lng - from_lng)
    lat1, lat2 = radians(from_lat), radians(to_lat)
    y = sin(d_lng) * cos(lat2)
    x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(d_lng)
    bearing = (degrees(atan2(y, x)) + 360) % 360
    dirs = (
        (22.5, "norr"),
        (67.5, "nordost"),
        (112.5, "öst"),
        (157.5, "sydost"),
        (202.5, "söder"),
        (247.5, "sydväst"),
        (292.5, "väst"),
        (337.5, "nordväst"),
        (360.0, "norr"),
    )
    for max_deg, name in dirs:
        if bearing < max_deg:
            return name
    return "norr"


async def list_district_contexts(session: AsyncSession) -> list[DistrictContext]:
    await ensure_catalog_defaults(session)
    row = await session.get(CatalogList, "ort")
    if row is None:
        return []
    return [
        DistrictContext(
            label=item.label,
            description=item.description,
            bounds=item.bounds,
        )
        for item in coerce_catalog_items(row.items)
    ]


async def get_district_context(
    session: AsyncSession,
    name: str,
) -> DistrictContext | None:
    needle = name.strip()
    if not needle or needle == "—":
        return None
    for ctx in await list_district_contexts(session):
        if ctx.label.casefold() == needle.casefold():
            return ctx
    return None


def format_area_block(
    ctx: DistrictContext,
    *,
    centrum: DistrictContext | None = None,
) -> str:
    lines = [f"Området {ctx.label}:"]
    if ctx.description:
        lines.append(ctx.description)
    center = ctx.center
    if center is not None and ctx.bounds is not None:
        lat, lng = center
        ns, ew = _extent_km(ctx.bounds)
        lines.append(
            f"Ungefärlig mittpunkt: lat {lat:.4f}, lng {lng:.4f}. "
            f"Utsträckning ca {ns:.1f} km N–S och {ew:.1f} km Ö–V."
        )
        if centrum is not None and centrum.center is not None and ctx.label != centrum.label:
            c_lat, c_lng = centrum.center
            dist = _haversine_km(c_lat, c_lng, lat, lng)
            direction = _cardinal(c_lat, c_lng, lat, lng)
            lines.append(
                f"Ligger ungefär {dist:.1f} km {direction} om Centrum."
            )
    return "\n".join(lines)


async def area_block_for_name(session: AsyncSession, name: str) -> str:
    districts = await list_district_contexts(session)
    by_label = {d.label.casefold(): d for d in districts}
    ctx = by_label.get(name.strip().casefold())
    if ctx is None:
        return ""
    centrum = by_label.get("centrum")
    return format_area_block(ctx, centrum=centrum)
