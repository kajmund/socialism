"""Deterministic utilities: money, dates, seeded randomness, JSON I/O."""
from __future__ import annotations

import hashlib
import json
import random
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from . import config

CENT = Decimal("0.01")
ROUND = ROUND_HALF_UP


def M(x: Any) -> Decimal:
    """Money: quantize to öre, half-up."""
    return Decimal(str(x)).quantize(CENT, ROUND)


def D(x: Any) -> Decimal:
    """Decimal without quantization (for rates)."""
    return Decimal(str(x))


def pct(x: Any) -> Decimal:
    """Percent literal: pct(31.42) -> 0.3142."""
    return D(x) / D(100)


def add_months(d: date, n: int) -> date:
    y, m = d.year, d.month - 1 + n
    y += m // 12
    m = m % 12 + 1
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return date(y, m, day)


def month_range(start: date, end: date) -> list[tuple[int, int]]:
    """Inclusive list of (year, month) tuples."""
    out = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return out


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def last_day_of_month(d: date) -> date:
    return add_months(date(d.year, d.month, 1), 1) - timedelta(days=1)


def days_between(a: date, b: date) -> int:
    return (b - a).days


def rng(name: str) -> random.Random:
    """Deterministic per-module random stream derived from the global seed."""
    h = hashlib.sha256(f"{config.SEED}:{name}".encode()).hexdigest()
    return random.Random(int(h[:15], 16))


def write_json(path: Path | str, obj: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def read_json(path: Path | str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fmt_sek(x: Any) -> str:
    """Swedish formatting of money: 1 234 567,89"""
    d = M(x)
    sign = "-" if d < 0 else ""
    d = abs(d)
    s = f"{d:.2f}".replace(".", ",")
    ip, fp = s.split(",")
    ip = " ".join([ip[::-1][i:i + 3] for i in range(0, len(ip), 3)])[::-1]
    return f"{sign}{ip},{fp}"


def fmt_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def fmt_date_sv(d: date) -> str:
    return d.strftime("%d.%m.%Y")
