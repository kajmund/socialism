"""SIE4 exporter + reader (SIE filformat, Utgåva 4C, 2025-08-06).

Exports a type 4E file per fiscal year: #FORMAT PC8 (CP437), LF line endings,
mandatory header/identification records, #KONTO/#KTYP, #IB/#UB/#RES for years
0 and -1, #DIM/#OBJEKT (1 kostnadsställe, 6 projekt) and #VER/#TRANS in
ascending voucher order. The reader round-trips balances and vouchers for
validation (check 16).
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from . import config
from .model import Model
from .util import M

RESULT_ACCOUNTS = {3011, 4520, 5010, 5020, 5060, 5420, 5615, 5616, 5800, 5910,
                   6072, 6110, 6210, 6310, 6351, 6420, 6540, 6570, 6991, 6992,
                   7210, 7290, 7410, 7510, 7610, 7699, 7831, 7832, 8313, 8410, 8910}
ZEROING_PREFIXES = ("Resultatöverföring", "Överföring till balanserat")
COST_ACCOUNTS = {4520, 5010, 5020, 5060, 5420, 5615, 5616, 5800, 5910, 6072,
                 6110, 6210, 6310, 6351, 6420, 6540, 6570, 6991, 6992, 7210,
                 7290, 7410, 7510, 7610, 7699, 7831, 7832, 8410}

_CP437_FIXES = {
    "–": "-", "—": "-", "…": "...", "\u2019": "'", "\u2018": "'",
    "\u201c": '"', "\u201d": '"', "≥": ">=", "≤": "<=", "\u00a0": " ",
    "é": "e", "è": "e", "ü": "u", "×": "x",
}


def _prev_day(iso: str) -> str:
    from datetime import date, timedelta
    y, m, d = map(int, iso.split("-"))
    return (date(y, m, d) - timedelta(days=1)).isoformat()


def _s(s: str) -> str:
    for k, v in _CP437_FIXES.items():
        s = s.replace(k, v)
    return s


def _fmt_amount(a) -> str:
    """SIE amounts: dot decimal, minus for credit, no thousands separators."""
    d = M(a)
    s = f"{abs(d):.2f}".rstrip("0").rstrip(".")
    if d < 0:
        s = "-" + s
    return s


class SieExport:
    def __init__(self, m: Model):
        self.m = m
        self.project_codes = {p["id"]: p["code"] for p in m.projects
                              if isinstance(p, dict)} if m.projects and isinstance(m.projects[0], dict) else {}
        if not self.project_codes:
            for p in m.projects:
                try:
                    self.project_codes[p.id] = p.code
                except AttributeError:
                    break

    # ------------------------------------------------------------------
    def _fy(self, fy_key):
        return tuple(map(int, config.FISCAL_YEARS[fy_key][0].isoformat().split("-"))), \
               tuple(map(int, config.FISCAL_YEARS[fy_key][1].isoformat().split("-")))

    def balances_at(self, upto: str) -> dict:
        bal = defaultdict(Decimal)
        for p in self.m.postings:
            if p["date"] <= upto:
                bal[p["account"]] += Decimal(p["amount"])
        return bal

    def res_for(self, lo: str, hi: str) -> dict:
        """Year activity per result account, excluding closing zeroing rows."""
        # lo is the fiscal start; exclude vouchers dated before it, include the
        # closing reversal vouchers dated on the first day of the new year.
        res = defaultdict(Decimal)
        for v in self.m.vouchers:
            if v["date"] > hi or v["date"] < lo:
                continue
            if v["text"].startswith(ZEROING_PREFIXES):
                continue
            for acc, amt in v["rows"]:
                if int(acc) in RESULT_ACCOUNTS:
                    res[int(acc)] += Decimal(amt)
        return res

    def export(self, fy_key: str, path: Path | str) -> str:
        (sy, sm, sd), (ey, em, ed) = self._fy(fy_key)
        start = f"{sy:04d}{sm:02d}{sd:02d}"
        end = f"{ey:04d}{em:02d}{ed:02d}"
        start_iso = f"{sy:04d}-{sm:02d}-{sd:02d}"
        end_iso = f"{ey:04d}-{em:02d}-{ed:02d}"
        prev = config.FISCAL_YEARS[fy_key][0].replace(year=config.FISCAL_YEARS[fy_key][0].year - 1)
        prev_start = prev.strftime("%Y%m%d")
        prev_end = f"{sy - 1:04d}0930"

        used = {p["account"] for p in self.m.postings}
        konto_lines = []
        for acc in self.m.accounts:
            n = acc["number"]
            if n in used:
                konto_lines.append(f'#KONTO {n} "{_s(acc["name"])}"')
                konto_lines.append(f'#KTYP {n} {acc["type"]}')

        # opening balances are the balances at the END of the previous fiscal year
        ib = self.balances_at(_prev_day(start_iso))
        ub = self.balances_at(end_iso)
        res = self.res_for(start_iso, end_iso)

        # objects
        dim_lines = ['#DIM 1 "Kostnadsställe"', '#DIM 6 "Projekt"',
                     '#OBJEKT 1 "STD" "Standard"']
        for pid, code in sorted(self.project_codes.items()):
            dim_lines.append(f'#OBJEKT 6 "{code}" "{code}"')

        L: list[str] = []
        L.append("#FLAGGA 0")
        L.append(f'#PROGRAM "SPEC-SME-GEN {config.VERSION}"')
        L.append("#FORMAT PC8")
        L.append("#GEN 20261018")
        L.append("#SIETYP 4")
        L.append("#FNAMN Nordviken Digital AB")
        L.append("#ORGNR 5592451673")
        L.append('#ADRESS "Kajplatsen 4, 115 27 Stockholm"')
        L.append("#FTYP AB")
        L.append("#KPTYP EUBAS97")
        L.append("#VALUTA SEK")
        L.append(f"#TAXAR {sy}")
        L.append(f"#RAR 0 {start} {end}")
        L.append(f"#RAR -1 {prev_start} {prev_end}")
        L.extend(konto_lines)
        L.extend(dim_lines)

        # balances: #IB 0, #UB 0, #RES 0, #IB -1 (= opening of previous year)
        all_accounts = sorted(used)
        for acc in all_accounts:
            if ib.get(acc):
                L.append(f"#IB 0 {acc} {_fmt_amount(ib[acc])}")
        for acc in all_accounts:
            if ub.get(acc):
                L.append(f"#UB 0 {acc} {_fmt_amount(ub[acc])}")
        for acc in sorted(res):
            if res[acc]:
                L.append(f"#RES 0 {acc} {_fmt_amount(res[acc])}")
        for acc in all_accounts:
            if ib.get(acc):
                L.append(f"#IB -1 {acc} {_fmt_amount(ib[acc])}")

        # vouchers ascending by series
        vouchers = sorted(self.m.vouchers, key=lambda v: (v["series"], v["id"]))
        in_fy = [v for v in vouchers if start_iso < v["date"] <= end_iso]
        for v in in_fy:
            rows = []
            for acc, amt in v["rows"]:
                objects = self._objects_for(v, int(acc))
                obj_s = " ".join(f'{{{o.split(" ")[0]} "{o.split(" ", 1)[1]}"}}'
                                 for o in objects)
                rows.append(f"#TRANS {acc} {obj_s} {_fmt_amount(amt)}".rstrip())
            L.append(f'#VER "{v["series"]}" "{v["id"].split("-")[-1]}" {v["date"].replace("-", "")} "{_s(v["text"])}"')
            L.append("{")
            L.extend(rows)
            L.append("}")

        text = "\n".join(L) + "\n"
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(text.encode("cp437"))
        return text

    def _objects_for(self, v, acc: int) -> list:
        if acc in (3011, 1510, 2611):
            pid = None
            for inv in self.m.customer_invoices:
                if inv.get("voucher_id") == v["id"]:
                    pid = inv.get("project_id")
                    break
            if pid and pid in self.project_codes:
                return [f"6 {self.project_codes[pid]}"]
            return []
        if acc in COST_ACCOUNTS or acc in (7210, 7510, 7410, 7290):
            return ["1 STD"]
        return []


# ------------------------------------------------------------------ reader
class SieReader:
    """Reads a SIE4 file back into accounts/balances/vouchers for round-trip."""

    def __init__(self):
        self.konton: dict[int, str] = {}
        self.saldon: dict[tuple[str, int, int], Decimal] = {}
        self.res: dict[tuple[int, int], Decimal] = {}
        self.ver: list[dict] = []
        self.sietyp = None
        self.format = None
        self.fnamn = None
        self.rar = {}

    def read(self, path: Path | str) -> "SieReader":
        raw = Path(path).read_bytes()
        text = raw.decode("cp437")
        current_voucher = None
        for line in text.splitlines():
            line = line.rstrip("\r")
            if not line.strip() or line.strip() == "{":
                if current_voucher and line.strip() == "{" and current_voucher.get("open"):
                    current_voucher["rows"] = []
                continue
            if line.strip() == "}":
                if current_voucher:
                    self.ver.append(current_voucher)
                    current_voucher = None
                continue
            tag, rest = line.split(" ", 1) if " " in line else (line, "")
            rest = rest.strip()
            if tag == "#KONTO":
                num, name = rest.split(" ", 1)
                self.konton[int(num)] = name.strip('"')
            elif tag in ("#IB", "#UB"):
                year, num, amt = rest.split(" ", 2)
                self.saldon[(tag[1:], int(year), int(num))] = Decimal(amt)
            elif tag == "#RES":
                year, num, amt = rest.split(" ", 2)
                self.res[(int(year), int(num))] = Decimal(amt)
            elif tag == "#VER":
                parts = rest.split(" ")
                series = parts[0].strip('"')
                vnum = parts[1].strip('"')
                date = parts[2]
                text = rest.split('"', 2)[2].rsplit('"', 1)[0] if '"' in rest else ""
                current_voucher = {"series": series, "num": int(vnum), "date": date,
                                   "text": text, "rows": [], "open": True}
            elif tag == "#TRANS" and current_voucher:
                parts = rest.split(" ")
                # account, {objects...}, amount
                acc = int(parts[0])
                amt = Decimal(parts[-1])  # amount is always the last field
                current_voucher["rows"].append((acc, amt))
            elif tag == "#SIETYP":
                self.sietyp = int(rest)
            elif tag == "#FORMAT":
                self.format = rest
            elif tag == "#FNAMN":
                self.fnamn = rest
            elif tag == "#RAR":
                y, a, b = rest.split(" ")
                self.rar[int(y)] = (a, b)
        return self
