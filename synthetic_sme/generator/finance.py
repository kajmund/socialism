"""Finance engine: double-entry bookkeeping for the whole 24-month history.

All postings derive from the canonical story (schedules, streams, employees,
events). The engine is deterministic; every voucher balances by construction.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from . import config
from .model import Model
from .util import M, add_months, last_day_of_month, month_key, month_range, pct, rng

D = date

# ---------------------------------------------------------------- chart
CHART = [
    # assets
    (1220, "Inventarier", "T"), (1229, "Ackumulerade avskrivningar inventarier", "T"),
    (1250, "Datorer och kringutrustning", "T"), (1259, "Ackumulerade avskrivningar datorer", "T"),
    (1510, "Kundfordringar", "T"), (1630, "Skattekonto", "T"),
    (1710, "Förutbetalda kostnader och upplupna intäkter", "T"),
    (1790, "Övriga interimsfordringar", "T"),
    (1930, "Företagskonto", "T"),
    # equity & liabilities
    (2081, "Aktiekapital", "S"), (2091, "Balanserat resultat", "S"), (2099, "Årets resultat", "S"),
    (2350, "Banklån", "S"), (2380, "Checkräkningskredit", "S"),
    (2440, "Leverantörsskulder", "S"), (2510, "Skatteskulder", "S"),
    (2611, "Utgående moms 25 %", "S"), (2614, "Utgående moms omvänd skattskyldighet", "S"),
    (2641, "Ingående moms", "T"), (2645, "Ingående moms omvänd skattskyldighet", "T"),
    (2650, "Redovisningskonto för moms", "S"),
    (2710, "Personalens källskatt", "S"), (2730, "Lagstadgade sociala avgifter", "S"),
    (2920, "Upplupna semesterlöner", "S"), (2940, "Upplupna sociala avgifter (semesterlön)", "S"),
    (2990, "Övriga upplupna kostnader", "S"),
    # income
    (3011, "Försäljning tjänster, 25 % moms", "I"),
    (3740, "Öres- och kronutjämning", "I"),
    # costs
    (4520, "Underkonsulter", "I"),
    (5010, "Lokalhyra", "I"), (5020, "El", "I"), (5060, "Städning", "I"),
    (5420, "Programvaror och licenser", "I"),
    (5615, "Leasingavgifter bilar", "I"), (5616, "Leasing IT-utrustning", "I"),
    (5800, "Resekostnader", "I"), (5910, "Marknadsföring", "I"),
    (6072, "Representation, ej avdragsgill", "I"),
    (6110, "Kontorsmaterial", "I"), (6210, "Telekommunikation", "I"),
    (6310, "Företagsförsäkringar", "I"), (6351, "Konstaterade kundförluster", "I"),
    (6420, "Ersättning till revisor", "I"), (6540, "Redovisningstjänster", "I"),
    (6570, "Bankkostnader", "I"),
    (6991, "Övriga externa kostnader, avdragsgilla", "I"),
    (6992, "Övriga externa kostnader, ej avdragsgilla", "I"),
    (7210, "Löner tjänstemän", "I"), (7290, "Förändring av semesterlöneskuld", "I"),
    (7410, "Pensionsförsäkringspremier", "I"), (7510, "Lagstadgade sociala avgifter", "I"),
    (7610, "Utbildning personal", "I"), (7699, "Övriga personalkostnader", "I"),
    (7831, "Avskrivningar inventarier", "I"), (7832, "Avskrivningar datorer", "I"),
    (8313, "Ränteintäkter", "I"), (8410, "Räntekostnader", "I"),
    (8910, "Skatt på årets resultat", "I"),
]

ACCOUNTS = {num: (name, ktype) for num, name, ktype in CHART}
DEBIT_ACCOUNTS = {"T"}   # assets + cost accounts debit-positive
VAT = pct(25)


class Ledger:
    def __init__(self):
        self.balances: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        self.vouchers: list[dict] = []
        self.postings: list[dict] = []
        self.vnum = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}
        self.year = None

    def _vid(self, series, d: date) -> str:
        self.vnum[series] += 1
        return f"{series}-{d.year}-{self.vnum[series]:03d}"

    def post(self, series, d, text, rows, event_id=None):
        """rows: list of (account, amount_signed). Debit positive, credit negative."""
        total = sum((M(a) for _, a in rows), Decimal("0"))
        assert total == 0, f"Voucher '{text}' unbalanced: {total}"
        vid = self._vid(series, d)
        p = []
        for acc, amount in rows:
            amt = M(amount)
            self.balances[acc] += amt
            p.append({"voucher_id": vid, "date": d.isoformat(), "account": acc,
                      "amount": str(amt), "event_id": event_id})
        self.vouchers.append({"id": vid, "series": series, "date": d.isoformat(),
                              "text": text[:50], "rows": [(a, str(M(b))) for a, b in rows],
                              "event_id": event_id})
        self.postings.extend(p)
        return vid

    def balance(self, acc: int) -> Decimal:
        return M(self.balances[acc])


class Engine:
    def __init__(self, model: Model):
        self.m = model
        self.led = Ledger()
        self.r = rng("finance")
        self.ar: list[dict] = []        # open customer invoices
        self.ap: list[dict] = []        # open supplier invoices
        self.paid_out: list[dict] = []
        self.paid_in: list[dict] = []
        self.bank: list[dict] = []      # 1930 movements
        self.inv_n = {"2024": 0, "2025": 0, "2026": 0}
        self.sin_n = {"2024": 0, "2025": 0, "2026": 0}
        self.kin_n = {"2024": 0, "2025": 0, "2026": 0}
        self.overdraft_drawn = Decimal("400000.00")   # 2380 credit balance (drawn)
        self.loan_balance = Decimal("800000.00")
        self.hours_invoiced: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))

    # ------------------------------------------------------------ opening
    def opening_balances(self):
        ib = {
            1220: 450_000, 1229: -180_000, 1250: 720_000, 1259: -260_000,
            1510: 4_200_000, 1630: -80_000, 1710: 63_000,
            1930: 2_600_000, 2350: -800_000, 2380: -400_000,
            2440: -900_000, 2510: -450_000, 2611: -480_000, 2710: -360_000,
            2730: -380_000, 2920: -1_900_000, 2940: -596_980, 2990: -85_000,
            2081: -250_000,
        }
        # 2091 balanserad vinst = plug (makes the opening balance sheet balance)
        plug = -sum(ib.values())
        assert plug < 0, "Opening balance plug positive - story inconsistent"
        ib[2091] = plug
        rows = [(acc, amt) for acc, amt in ib.items()]
        self.led.post("A", D(2024, 9, 30), "Ingående balans 2024-10-01 (per 2024-09-30)", rows)
        self.m.secret["ib_2091_plug"] = str(-plug)
        # opening receivables: September 2024 invoices collected Oct-Nov 2024
        self.seed_opening_ar()
        self.seed_opening_ap()

    def seed_opening_ap(self):
        """Opening payables (IB 2440 = 900 000 kr): September 2024 supplier invoices."""
        entries = [
            ("SUP-003", 280_000, "2024-10-25", "M365 och Azure (september)"),
            ("SUP-001", 165_000, "2024-10-10", "Lokalhyra september"),
            ("SUP-034", 136_000, "2024-10-28", "Underkonsulter september"),
            ("SUP-005", 49_000, "2024-10-28", "Ärendehantering september"),
            ("SUP-040", 18_000, "2024-10-28", "Redovisning september"),
            ("SUP-035", 39_200, "2024-10-28", "Underkonsult Dataverket september"),
            ("SUP-037", 35_600, "2024-10-28", "Underkonsult Pixel & Form september"),
        ]
        total = 900_000 - sum(g for _, g, _, _ in entries)
        entries.append(("SUP-025", total, "2024-10-28", "Pensionspremier september"))
        for i, (sid, gross, due, label) in enumerate(entries, start=1):
            gross = M(gross)
            net = M(gross / Decimal("1.25"))
            inv = {"id": f"SIN-2024-{i:04d}-IB", "supplier_id": sid, "stream_id": None,
                   "date": "2024-09-28", "due_date": due, "account": "5420",
                   "label": label + " (ingående skuld)", "net": str(net),
                   "vat": str(M(gross - net)), "gross": str(gross),
                   "reverse_charge": False, "voucher_id": None, "status": "OPEN",
                   "event_id": None}
            self.m.supplier_invoices.append(inv)
            self.ap.append(inv)

    def seed_opening_ar(self):
        entries = [
            ("CUS-001", 1_875_000, "2024-10-15"),
            ("CUS-002", 362_500, "2024-10-28"),
            ("CUS-003", 250_000, "2024-11-13"),
            ("CUS-005", 330_000, "2024-10-28"),
            ("CUS-007", 350_000, "2024-11-13"),
            ("CUS-011", 250_000, "2024-10-28"),
            ("CUS-013", 275_000, "2024-10-28"),
            ("CUS-016", 157_500, "2024-10-28"),
            ("CUS-026", 60_000, "2024-10-28"),
            ("CUS-027", 80_000, "2024-10-28"),
            ("CUS-030", 60_000, "2024-10-28"),
            ("CUS-033", 50_000, "2024-10-28"),
            ("CUS-039", 50_000, "2024-10-28"),
            ("CUS-041", 50_000, "2024-10-28"),
            ("CUS-049", 0, "2024-11-28"),  # plug below
        ]
        total = sum(g for _, g, _ in entries)
        entries[-1] = ("CUS-049", 4_200_000 - total, "2024-11-28")
        for i, (cid, gross, due) in enumerate(entries, start=1):
            gross = M(gross)
            net = M(gross / Decimal("1.25"))
            inv = {"id": f"INV-2024-{i:04d}-IB", "customer_id": cid, "schedule_id": None,
                   "contract_id": None, "project_id": None,
                   "date": "2024-09-28", "month": "2024-09", "due_date": due,
                   "net": str(net), "vat": str(M(gross - net)), "gross": str(gross),
                   "hours": None, "rate": None, "voucher_id": None, "status": "OPEN",
                   "note": "Ingående kundfordran (fakturerad 2024-09-28)",
                   "event_id": None, "anomaly": None}
            self.m.customer_invoices.append(inv)
            self.ar.append(inv)

    # ------------------------------------------------------------ helpers
    def _inv_id(self, kind, d):
        n = self.inv_n[str(d.year)] + 1
        self.inv_n[str(d.year)] = n
        return f"{kind}-{d.year}-{n:04d}"

    def _sin_id(self, d):
        n = self.sin_n[str(d.year)] + 1
        self.sin_n[str(d.year)] = n
        return f"SIN-{d.year}-{n:04d}"

    def _bank_txn(self, d, amount, text, ref=""):
        self.bank.append({"date": d.isoformat(), "amount": str(M(amount)), "text": text, "ref": ref})

    def _pay_from_bank(self, d, amount, text, ref=""):
        self._bank_txn(d, -M(amount), text, ref)
        return M(amount)

    def _recv_to_bank(self, d, amount, text, ref=""):
        self._bank_txn(d, M(amount), text, ref)
        return M(amount)

    def _event_voucher(self, evt_id, series, d, text, rows):
        vid = self.led.post(series, d, text, rows, event_id=evt_id)
        ev = next(e for e in self.m.events if e.id == evt_id)
        ev.voucher_ids = [vid]
        return vid

    # ------------------------------------------------------------ months
    def run(self):
        self.opening_balances()
        months = month_range(config.HIST_START, config.HIST_END)
        for (y, m) in months:
            self.run_month(y, m)
            if (y, m) == (2025, 9):
                self.close_year(D(2025, 9, 30))
            if (y, m) == (2026, 9):
                self.close_year(D(2026, 9, 30))
        self.m.accounts = [{"number": n, "name": nm, "type": k} for n, (nm, k) in ACCOUNTS.items()]
        self.m.vouchers = self.led.vouchers
        self.m.postings = self.led.postings
        self.m.payments_in = self.paid_in
        self.m.payments_out = self.paid_out
        self.m.bank_txns = self.bank

    def run_month(self, y, m):
        r = self.r
        mk = month_key(D(y, m, 1))
        d1 = D(y, m, 1)
        dlast = last_day_of_month(d1)
        # 0. VAT + skattekonto settlement on the 12th (for previous month) FIRST:
        #    at this point no current-month postings exist, so balances equal
        #    exactly the previous month's outstanding amounts.
        self.tax_account_settlement(y, m)
        # 1. customer invoicing on the 28th
        self.invoice_customers(y, m, mk)
        # 2. supplier invoicing (streams + one-offs)
        self.invoice_suppliers(y, m, mk)
        # 3. payroll on the 25th
        self.run_payroll(y, m)
        # 4. customer payments
        self.collect_customer_payments(y, m, dlast)
        # 5. supplier payments + fixed monthly outflows
        self.pay_suppliers(y, m, dlast)
        # 6. loan payment on the 5th, bank fees, interest
        self.loan_and_fees(y, m)
        # 7. depreciation, prepaid amortization
        self.depreciation_and_prepaid(y, m, mk)
        # 8. credit note refund (TS) and bad-debt write-off (Sjöstadens Bryggeri)
        if (y, m) == (2026, 8):
            self.settle_credit_note_refund()
        if (y, m) == (2025, 12):
            self.write_off_bad_debt()
        # 9. overdraft management at month end
        self.manage_overdraft(y, m)

    # ------------------------------------------------------------ invoicing
    def rate_for(self, sched, mk, anomalies=False):
        """Effective billed rate for month key (with anomaly behaviour)."""
        base = sched.rate
        current = base
        applied = {}
        for k in sorted(sched.rate_changes):
            if k <= mk:
                current = sched.rate_changes[k]
        if anomalies and mk in sched.anomalies and sched.anomalies[mk] == "UNDERBILL_RATE":
            # bill the pre-change rate (the mistake)
            current = sched.rate
        return current

    def invoice_customers(self, y, m, mk):
        d = D(y, m, 28)
        for sched in self.m.schedules:
            if sched.billing_model in ("TIME",):
                if mk not in sched.monthly_hours:
                    continue
                hours = Decimal(str(sched.monthly_hours[mk]))
                rate = self.rate_for(sched, mk, anomalies=True)
                net = M(hours * rate)
                if net == 0:
                    continue
                self._customer_invoice(sched, d, mk, net, hours=hours, rate=rate,
                                      anomaly=sched.anomalies.get(mk))
            elif sched.billing_model in ("FIXED", "MANAGED"):
                if mk not in sched.monthly_amount:
                    continue
                net = M(sched.monthly_amount[mk])
                if net == 0:
                    continue
                self._customer_invoice(sched, d, mk, net, hours=None, rate=None, anomaly=None)

        # special: FS-Intranät slutfaktura (efter periodens slut)
        if (y, m) == (2025, 10):
            sched = self.m.schedule("SCH-005")
            self._customer_invoice(sched, D(2025, 10, 10), "2025-09", M(300_000),
                                   hours=None, rate=None, anomaly=None, invoice_date=D(2025, 10, 10),
                                   note="Slutfaktura, fakturerad efter periodens slut", event=None)
        # special: KF catch-up invoice 2026-02-28
        if (y, m) == (2026, 2):
            sched = self.m.schedule("SCH-008")
            missing = Decimal("0")
            for k in ("2025-11", "2025-12", "2026-01"):
                missing += Decimal(str(sched.monthly_hours.get(k, 0)))
            net = M(missing * 100)  # (1150-1050) per hour
            self._customer_invoice(sched, D(2026, 2, 28), "2026-02", net, hours=None, rate=None,
                                   anomaly=None, note="Eftersläpningsfaktura index nov 2025–jan 2026",
                                   event="EVT-049")
        # special: TS credit note 2026-06-30
        if (y, m) == (2026, 6):
            self.credit_note(D(2026, 6, 30), "CUS-006", "SCH-009", M(72_000),
                             "Kreditnota viteförlikning TS-Produktionsportal", "EVT-061")

    def _customer_invoice(self, sched, d, mk, net, hours=None, rate=None, anomaly=None,
                          invoice_date=None, note="", event=None):
        cus = self.m.customer(sched.customer_id)
        inv_id = self._inv_id("INV", d)
        vat = M(net * VAT)
        gross = M(net + vat)
        idate = invoice_date or d
        due = idate + timedelta(days=cus.credit_days)
        text = f"Kundfaktura {cus.name} {sched.id} {mk}"
        rows = [(1510, gross), (3011, -net), (2611, -vat)]
        vid = self.led.post("B", idate, text, rows, event_id=event)
        inv = {"id": inv_id, "customer_id": cus.id, "schedule_id": sched.id,
               "contract_id": sched.contract_id, "project_id": sched.project_id,
               "date": idate.isoformat(), "month": mk, "due_date": due.isoformat(),
               "net": str(net), "vat": str(vat), "gross": str(gross),
               "hours": str(hours) if hours is not None else None,
               "rate": rate, "voucher_id": vid, "status": "OPEN",
               "note": note, "event_id": event, "anomaly": anomaly}
        self.m.customer_invoices.append(inv)
        self.ar.append(inv)
        if event:
            ev = next(e for e in self.m.events if e.id == event)
            ev.invoice_ids.append(inv_id)
        return inv

    def credit_note(self, d, customer_id, schedule_id, net, text, event=None):
        vat = M(net * VAT)
        gross = M(net + vat)
        kin_id = self._inv_id("KIN", d)
        rows = [(3011, net), (2611, vat), (1510, -gross)]
        vid = self.led.post("B", d, text, rows, event_id=event)
        inv = {"id": kin_id, "customer_id": customer_id, "schedule_id": schedule_id,
               "date": d.isoformat(), "due_date": "", "month": d.strftime("%Y-%m"),
               "net": str(-net), "vat": str(-vat), "gross": str(-gross),
               "voucher_id": vid, "status": "CREDIT_NOTE", "note": text, "event_id": event}
        self.m.customer_invoices.append(inv)
        self.ar.append(inv)  # negative amount: reduces the balance
        if event:
            ev = next(e for e in self.m.events if e.id == event)
            ev.invoice_ids.append(kin_id)

    # ------------------------------------------------------------ suppliers
    def invoice_suppliers(self, y, m, mk):
        r = self.r
        for stream in self.m.streams:
            if stream.id == "STR-038":
                # annual insurance invoice in January; monthly cost via prepaid
                if (y, m) == (2025, 1) or (y, m) == (2026, 1):
                    self._supplier_invoice(stream, D(y, m, 12), M(252_000), "Årspremie företagsförsäkring",
                                           to_prepaid=True)
                continue
            if stream.id == "STR-024":
                continue  # pension premium: filled by payroll
            amt = stream.monthly_amount.get(mk)
            if not amt or amt <= 0:
                continue
            day = 3 + (r.randint(0, 100) % 21)
            self._supplier_invoice(stream, D(y, m, min(day, 28)), M(amt), stream.label)

        # one-off supplier invoices from events
        self.one_off_invoices(y, m)

    def _supplier_invoice(self, stream, d, net, label, to_prepaid=False, event_id=None):
        sup = self.m.supplier(stream.supplier_id)
        sid = self._sin_id(d)
        vat = M(net * VAT)
        gross = M(net + vat)
        text = f"Lev.faktura {sup.name} {label}"
        if stream.reverse_charge:
            rows = [(int(stream.account), net), (2440, -net), (2645, vat), (2614, -vat)]
        elif to_prepaid:
            rows = [(1710, net), (2641, vat), (2440, -gross)]
        else:
            rows = [(int(stream.account), net), (2641, vat), (2440, -gross)]
        vid = self.led.post("C", d, text, rows, event_id=event_id)
        due = d + timedelta(days=sup.payment_days)
        inv = {"id": sid, "supplier_id": sup.id, "stream_id": stream.id,
               "date": d.isoformat(), "due_date": due.isoformat(), "account": stream.account,
               "label": label, "net": str(net), "vat": str(vat), "gross": str(gross),
               "reverse_charge": stream.reverse_charge, "voucher_id": vid,
               "status": "OPEN", "event_id": event_id}
        self.m.supplier_invoices.append(inv)
        self.ap.append(inv)
        return inv

    def one_off_invoices(self, y, m):
        """Hardware purchases (assets), legal, recruiting, training, marketing one-offs."""
        plan = {
            (2024, 10): [("SUP-031", "7699", 85_000, "Rekrytering DevOps (Patrik Öberg)", "EVT-003")],
            (2024, 11): [("SUP-002", None, 350_000, "20 laptops + skärmar (aktiveras)", "EVT-006"),
                         ("SUP-038", "7699", 4_000, "Friskvårdsersättningar", None)],
            (2024, 12): [("SUP-026", "6072", 4_200, "Representation kundmiddag", None)],
            (2025, 2):  [("SUP-038", "7699", 3_600, "Friskvårdsersättningar", None)],
            (2025, 3):  [("SUP-002", None, 480_000, "Servrar och nätverksutrustning (aktiveras)", "EVT-015"),
                         ("SUP-031", "7699", 85_000, "Rekrytering junior utvecklare", "EVT-018"),
                         ("SUP-032", "7610", 48_000, "Certifieringskurser", None)],
            (2025, 4):  [("SUP-033", "6991", 48_000, "Arbetsrättstvist – utredning", "EVT-020")],
            (2025, 5):  [("SUP-038", "7699", 4_000, "Friskvårdsersättningar", None)],
            (2025, 6):  [("SUP-026", "6072", 3_800, "Representation sommarfest kunder", None)],
            (2025, 7):  [("SUP-031", "7699", 85_000, "Rekrytering DevOps (Simon Dahl)", "EVT-025")],
            (2025, 8):  [("SUP-002", None, 250_000, "Möbler nya kontorsplatser (inventarier)", "EVT-026"),
                         ("SUP-033", "6991", 36_000, "Förlikningsförhandling", "EVT-027")],
            (2025, 9):  [("SUP-026", "5910", 60_000, "Höstkampanj", None),
                         ("SUP-038", "7699", 3_200, "Friskvårdsersättningar", None)],
            (2025, 11): [("SUP-039", "6420", 95_000, "Revision FY2025", "EVT-037"),
                         ("SUP-038", "7699", 4_000, "Friskvårdsersättningar", None)],
            (2026, 2):  [("SUP-031", "7699", 90_000, "Rekrytering arkitekt (Nadia Haddad)", "EVT-057"),
                         ("SUP-033", "6991", 22_000, "Tilläggsavtal SE-Billing", "EVT-045"),
                         ("SUP-038", "7699", 3_800, "Friskvårdsersättningar", None)],
            (2026, 4):  [("SUP-032", "7610", 52_000, "AI-utbildning", None)],
            (2026, 5):  [("SUP-026", "5910", 45_000, "Rekryteringskampanj", None),
                         ("SUP-038", "7699", 4_000, "Friskvårdsersättningar", None)],
            (2026, 8):  [("SUP-038", "7699", 3_600, "Friskvårdsersättningar", None)],
            (2026, 9):  [("SUP-026", "5910", 85_000, "Kundevent/kickoff", None)],
        }
        for (sup_id, account, net, label, evt) in plan.get((y, m), []):
            if account is None:
                # asset purchase
                if "laptop" in label or "Servrar" in label or "arbetsstation" in label.lower():
                    self._asset_purchase(D(y, m, 15), sup_id, net, "1250", label, evt)
                else:
                    self._asset_purchase(D(y, m, 15), sup_id, net, "1220", label, evt)
            else:
                sup = self.m.supplier(sup_id)
                sid = self._sin_id(D(y, m, 15))
                vat = M(net * VAT)
                gross = M(net + vat)
                # friskvård och representation: moms ej avdragsgill -> bruttobokas
                if account == "6072" or label.startswith("Friskvård"):
                    rows = [(int(account), gross), (2440, -gross)]
                else:
                    rows = [(int(account), net), (2641, vat), (2440, -gross)]
                vid = self.led.post("C", D(y, m, 15), f"Lev.faktura {sup.name} {label}", rows, event_id=evt)
                inv = {"id": sid, "supplier_id": sup_id, "stream_id": None, "date": D(y, m, 15).isoformat(),
                       "due_date": (D(y, m, 15) + timedelta(days=30)).isoformat(), "account": account,
                       "label": label, "net": str(net), "vat": str(vat), "gross": str(gross),
                       "reverse_charge": False, "voucher_id": vid, "status": "OPEN", "event_id": evt}
                self.m.supplier_invoices.append(inv)
                self.ap.append(inv)

    def _asset_purchase(self, d, sup_id, net, asset_acct, label, evt):
        sup = self.m.supplier(sup_id)
        sid = self._sin_id(d)
        vat = M(net * VAT)
        gross = M(net + vat)
        vid = self.led.post("C", d, f"Lev.faktura {sup.name} {label}",
                            [(int(asset_acct), net), (2641, vat), (2440, -gross)], event_id=evt)
        inv = {"id": sid, "supplier_id": sup_id, "stream_id": None, "date": d.isoformat(),
               "due_date": (d + timedelta(days=30)).isoformat(), "account": asset_acct,
               "label": label, "net": str(net), "vat": str(vat), "gross": str(gross),
               "reverse_charge": False, "voucher_id": vid, "status": "OPEN", "event_id": evt}
        self.m.supplier_invoices.append(inv)
        self.ap.append(inv)
        self.m.assets.append({"date": d.isoformat(), "account": asset_acct, "label": label,
                              "amount": str(net), "supplier_id": sup_id})
        if evt:
            ev = next(e for e in self.m.events if e.id == evt)
            ev.voucher_ids = [vid]

    # ------------------------------------------------------------ payroll
    def salary_at(self, emp, d: date) -> int:
        amt = emp.salary[0].amount
        for s in emp.salary:
            if s.from_date <= d:
                amt = s.amount
        return amt

    def withholding_pct(self, emp) -> int:
        return 28 + (emp.emp_no * 7) % 8

    def active_employees(self, d: date):
        return [e for e in self.m.employees if e.hired <= d and (e.left is None or e.left >= d)]

    def gross_intjanande(self, emp, start: date, end: date):
        """Gross paid to employee within [start, end] (for vacation pay)."""
        tot = 0
        for (y, m) in month_range(start, end):
            payday = D(y, m, 25)
            if emp.hired <= payday and (emp.left is None or emp.left > payday):
                tot += self.salary_at(emp, payday)
        return tot

    def run_payroll(self, y, m):
        payday = D(y, m, 25)
        emps = self.active_employees(payday)
        gross = M(sum(self.salary_at(e, payday) for e in emps))
        # avgångsvederlag Tobias (förlikning), utbetalt september 2025
        severance = M(141_000) if (y, m) == (2025, 9) else M(0)
        total_gross = M(gross + severance)
        # vacation payout in June
        vacation_pay = M(0)
        if m == 6:
            window_start = D(y - 1, 4, 1)
            window_end = D(y, 3, 31)
            vacation_pay = M(sum(pct(12) * self.gross_intjanande(e, window_start, window_end) for e in emps))
        # pension premium
        ibb = config.TAX["ibb"][str(payday.year)]
        cap = M(7.5 * ibb / 12)
        pension = M(0)
        for e in emps:
            s = M(self.salary_at(e, payday))
            below = min(s, cap)
            above = max(s - cap, M(0))
            pension += M(pct(4.5) * below + pct(30) * above)
        # fees
        agi_base = total_gross + vacation_pay
        agi = M(pct(config.TAX["employer_fee_pct"]) * agi_base)
        withholding = M(sum(pct(self.withholding_pct(e)) * M(self.salary_at(e, payday)) for e in emps))
        sev_withhold = M(pct(31) * severance)
        withholding += sev_withhold
        if m == 6:
            withholding += M(pct(31) * vacation_pay)
        net_pay = M(total_gross + vacation_pay - withholding)
        # rows
        rows = [(7210, total_gross), (7510, agi), (7410, pension),
                (2710, -withholding), (2730, -(agi + pension)), (1930, -net_pay)]
        if m == 6:
            agi_v = M(pct(config.TAX["employer_fee_pct"]) * vacation_pay)
            rows.append((2920, vacation_pay))   # skulden minskar med utbetalningen
            rows.append((2940, agi_v))          # frisläppt avgift
            rows.append((7510, -agi_v))         # kostnaden neutraliseras (redan periodiserad)
        vid = self.led.post("D", payday, f"Lönekörning {y}-{m:02d}", rows)
        # pension premium is invoiced by Pensionsvalet (paid from the 2730 liability)
        if pension > 0:
            sup = self.m.supplier("SUP-025")
            sid = self._sin_id(D(y, m, 26))
            vat = M(pension * VAT)
            p_gross = M(pension + vat)
            p_vid = self.led.post("C", D(y, m, 26), f"Lev.faktura {sup.name} Pensionspremier",
                                 [(2730, pension), (2641, vat), (2440, -p_gross)])
            inv = {"id": sid, "supplier_id": "SUP-025", "stream_id": "STR-024",
                   "date": D(y, m, 26).isoformat(),
                   "due_date": (D(y, m, 26) + timedelta(days=30)).isoformat(),
                   "account": "7410", "label": "Pensionspremier",
                   "net": str(pension), "vat": str(vat), "gross": str(p_gross),
                   "reverse_charge": False, "voucher_id": p_vid, "status": "OPEN", "event_id": None}
            self.m.supplier_invoices.append(inv)
            self.ap.append(inv)
        # vacation liability accrual (12 % of regular gross, net of payouts)
        self.vacation_accrual(y, m, gross, vacation_pay)
        self.m.payroll_runs.append({
            "month": month_key(D(y, m, 1)), "pay_date": payday.isoformat(),
            "employees": len(emps), "gross": str(gross), "severance": str(severance),
            "vacation_pay": str(vacation_pay), "pension_premium": str(pension),
            "employer_fee": str(agi), "withholding": str(withholding), "net_pay": str(net_pay),
            "voucher_id": vid})
        # bank payment
        self._pay_from_bank(payday, net_pay, f"Löner {y}-{m:02d}", vid)

    def vacation_accrual(self, y, m, gross, vacation_pay):
        """Monthly accrual: 12 % of gross credited to the skuld. The June payout
        reduces the skuld via the payroll rows; the AGI side follows the same pattern."""
        accrual = M(pct(12) * gross)
        self.led.post("D", D(y, m, 25), f"Semesterlöneskuld {y}-{m:02d}",
                      [(7290, accrual), (2920, -accrual)])
        agi_delta = M(pct(config.TAX["employer_fee_pct"]) * accrual)
        self.led.post("D", D(y, m, 25), f"Sociala avgifter semesterlön {y}-{m:02d}",
                      [(7510, agi_delta), (2940, -agi_delta)])

    # ------------------------------------------------------------ payments
    def delay_days(self, profile):
        r = self.r
        if profile == "prepay":
            return -10
        if profile == "slow":
            return 12 + r.randint(0, 18)
        if profile == "very_slow":
            return 20 + r.randint(0, 25)
        return r.randint(-3, 7)

    def collect_customer_payments(self, y, m, dlast):
        for inv in list(self.ar):
            if inv["status"] != "OPEN" and inv["status"] != "CREDIT_NOTE":
                continue
            if inv["id"].startswith("KIN"):
                continue
            cus = self.m.customer(inv["customer_id"])
            due = D.fromisoformat(inv["due_date"])
            if inv["customer_id"] == "CUS-010":
                if inv.get("month") == "2025-10":
                    # October paid late, exactly once
                    if (y, m) == (2025, 11) and inv["status"] == "OPEN":
                        self._apply_payment(inv, M(inv["gross"]), D(2025, 11, 20),
                                            "Betalning (för sent, strax före konkursen)")
                    continue
                if (y, m) >= (2025, 11):
                    continue  # November and later: never paid, written off 2025-12-31
                # earlier months fall through to normal collection
            if inv["customer_id"] == "CUS-009" and inv.get("month") == "2025-02":
                # disputed final invoice: customer paid gross minus 96,800
                if (y, m) == (2025, 4) and inv["status"] == "OPEN":
                    paid = M(inv["gross"]) - M(96_800)
                    self._apply_payment(inv, paid, D(2025, 4, 20),
                                        "Delbetalning; 96 800 kr hålls inne (tvist)")
                continue
            pay_date = due + timedelta(days=self.delay_days(cus.payment_profile))
            if pay_date <= dlast:
                self._apply_payment(inv, M(inv["gross"]), pay_date, "Kundbetalning")

    def settle_credit_note_refund(self):
        """TS credit note (90 000 kr) refunded to customer 2026-08-15."""
        for inv in self.ar:
            if inv["id"].startswith("KIN") and inv["customer_id"] == "CUS-006":
                amount = M(abs(Decimal(inv["gross"])))
                inv["status"] = "SETTLED"
                inv["paid_date"] = "2026-08-15"
                vid = self.led.post("A", D(2026, 8, 15), "Återbetalning kreditnota TS",
                                    [(1510, amount), (1930, -amount)])
                self._pay_from_bank(D(2026, 8, 15), amount, "Återbetalning kreditnota", vid)
                self.paid_out.append({"invoice_id": inv["id"], "date": "2026-08-15",
                                      "amount": str(amount), "voucher_id": vid,
                                      "note": "Återbetalning kreditnota"})
                return

    def write_off_bad_debt(self):
        """Sjöstadens Bryggeri: konstaterad kundförlust 2025-12-31 (exact invoice total)."""
        total = M(0)
        for inv in self.ar:
            if inv["customer_id"] == "CUS-010" and inv["status"] == "OPEN":
                total += M(inv["gross"])
                inv["status"] = "WRITTEN_OFF"
                inv["paid_date"] = "2025-12-31"
        if total > 0:
            vid = self.led.post("A", D(2025, 12, 31), "Kundförlust Sjöstadens Bryggeri (konkurs)",
                                [(6351, total), (1510, -total)], event_id="EVT-040")
            ev = next(e for e in self.m.events if e.id == "EVT-040")
            ev.voucher_ids = [vid]
            self.m.secret["bad_debt_amount"] = str(total)

    def _apply_payment(self, inv, amount, d, note):
        inv["status"] = "PAID" if M(inv["gross"]) == M(amount) else "PARTIAL"
        inv["paid_amount"] = str(M(amount))
        inv["paid_date"] = d.isoformat()
        vid = self.led.post("A", d, f"Betalning {inv['id']} {note[:30]}",
                            [(1930, amount), (1510, -amount)])
        self.paid_in.append({"invoice_id": inv["id"], "date": d.isoformat(),
                             "amount": str(M(amount)), "voucher_id": vid, "note": note})
        self._recv_to_bank(d, amount, f"Inbetalning {inv['id']}", vid)

    def pay_suppliers(self, y, m, dlast):
        for inv in list(self.ap):
            if inv["status"] != "OPEN":
                continue
            due = D.fromisoformat(inv["due_date"])
            r = self.r
            pay_date = due + timedelta(days=r.randint(-2, 6))
            # liquidity policy: defer supplier payments when cash is strained
            if pay_date <= dlast and self.led.balance(1930) >= 500_000:
                self._pay_supplier_inv(inv, pay_date)

    def _pay_supplier_inv(self, inv, d):
        inv["status"] = "PAID"
        inv["paid_date"] = d.isoformat()
        # reverse-charge invoices are paid NET (the VAT is declared, not paid to the supplier)
        pay = M(inv["net"]) if inv.get("reverse_charge") else M(inv["gross"])
        vid = self.led.post("A", d, f"Betalning {inv['id']} {inv['label'][:28]}",
                            [(2440, pay), (1930, -pay)])
        self.paid_out.append({"invoice_id": inv["id"], "date": d.isoformat(),
                              "amount": str(pay), "voucher_id": vid})
        self._pay_from_bank(d, pay, f"Utbetalning {inv['id']}", vid)

    # ------------------------------------------------------------ loan/fees
    def loan_and_fees(self, y, m):
        d = D(y, m, 5)
        if self.loan_balance > 0:
            interest = M(self.loan_balance * pct(config.BANK["loan_rate_pct"]) / 12)
            amort = min(M(config.BANK["loan_monthly_payment"] - interest), self.loan_balance)
            self.loan_balance -= amort
            vid = self.led.post("A", d, "Banklån amortering och ränta",
                                [(2350, amort), (8410, interest), (1930, -M(amort + interest))])
            self._pay_from_bank(d, M(amort + interest), "Lånebetalning", vid)
        # bank fees
        d2 = D(y, m, 28)
        fees = M(950 + 300)
        vid = self.led.post("A", d2, "Bankavgifter", [(6570, fees), (1930, -fees)])
        self._pay_from_bank(d2, fees, "Bankavgifter", vid)
        # overdraft interest on drawn balance (month end)
        de = D(y, m, 28)
        od_int = M(self.overdraft_drawn * pct(config.BANK["overdraft_rate_pct"]) / 12)
        if od_int > 0:
            vid = self.led.post("A", de, "Ränta checkräkningskredit", [(8410, od_int), (1930, -od_int)])
            self._pay_from_bank(de, od_int, "Ränta checkkredit", vid)

    # ------------------------------------------------------------ dep/prepaid
    def depreciation_and_prepaid(self, y, m, mk):
        dlast = last_day_of_month(D(y, m, 1))
        # computers: 720k IB + 350k (2024-11) + 480k (2025-03) + 520k (2026-01)
        comp_cost = Decimal("720000")
        eq_cost = Decimal("450000")
        if mk >= "2024-11":
            comp_cost += Decimal("350000")
        if mk >= "2025-03":
            comp_cost += Decimal("480000")
        if mk >= "2026-01":
            comp_cost += Decimal("520000")
        if mk >= "2025-08":
            eq_cost += Decimal("250000")
        dep_c = M(comp_cost / 36)
        dep_e = M(eq_cost / 60)
        self.led.post("A", dlast, f"Avskrivningar {mk}",
                      [(7832, dep_c), (1259, -dep_c), (7831, dep_e), (1229, -dep_e)])
        # insurance prepaid amortization 21k/month
        self.led.post("A", dlast, f"Periodisering försäkring {mk}",
                      [(6310, M(21_000)), (1710, -M(21_000))])

    # ------------------------------------------------------------ taxes
    def tax_account_settlement(self, y, m):
        """On the 12th: settle the PREVIOUS month's VAT, payroll taxes and
        preliminary tax. Runs first in the month, so live balances equal the
        previous month's outstanding amounts."""
        prev = add_months(D(y, m, 1), -1)
        d = D(y, m, 12)
        # transfer VAT balances to the settlement account
        rows = []
        transfer_sum = Decimal("0")
        for src in (2611, 2614):
            b = self.led.balance(src)
            if b != 0:
                rows.append((src, -b))
                rows.append((2650, b))
                transfer_sum += b
        for src in (2641, 2645):
            b = self.led.balance(src)
            if b != 0:
                rows.append((2650, -b))
                transfer_sum -= b
                rows.append((src, -b))
        vat_net = M(-(self.led.balance(2650) + transfer_sum))
        if vat_net != 0:
            rows.append((2650, vat_net))
        ksk = M(-self.led.balance(2710))
        if ksk != 0:
            rows.append((2710, ksk))
        agi_skuld = M(-self.led.balance(2730))
        if agi_skuld != 0:
            rows.append((2730, agi_skuld))
        prelim = M(25_000 if (y, m) <= (2025, 9) else 30_000)
        rows.append((2510, prelim))
        # pay prior-year final tax
        if (y, m) == (2025, 6):
            rows.append((2510, M(450_000)))  # slutlig skatt FY2024
        if (y, m) == (2026, 6):
            fy25 = self.m.secret.get("tax_FY2025", {})
            if fy25 and fy25.get("payable"):
                rows.append((2510, M(fy25["payable"])))  # slutlig skatt FY2025
        if rows:
            rows.append((1630, -sum((Decimal(b) for _, b in rows), Decimal("0"))))
            self.led.post("E", d, f"Skattekonto och moms {prev.year}-{prev.month:02d}", rows)
        # pay the net skattekonto balance from bank (credit balance = payable)
        net = self.led.balance(1630)
        target = M(-80_000)  # IB credit kept as buffer
        if net < target:
            pay = M(target - net)
            vid = self.led.post("A", D(y, m, 15), "Betalning skattekonto",
                                [(1630, pay), (1930, -pay)])
            self._pay_from_bank(D(y, m, 15), pay, "Betalning skattekonto", vid)

    def manage_overdraft(self, y, m):
        limit = M(config.BANK["overdraft_limit"])
        dlast = last_day_of_month(D(y, m, 1))
        bal = self.led.balance(1930)
        if bal < 150_000:
            need = M(((150_000 - bal) // 10_000 + 1) * 10_000)
            room = limit - self.overdraft_drawn
            draw = min(need, room)
            if draw > 0:
                self.led.post("A", dlast, "Uttag checkräkningskredit",
                              [(1930, draw), (2380, -draw)])
                self.overdraft_drawn += draw
        elif bal > 600_000:
            extra = M(((bal - 600_000) // 10_000) * 10_000)
            if extra > 0:
                repay = min(extra, self.overdraft_drawn)
                if repay > 0:
                    self.led.post("A", dlast, "Amortering checkräkningskredit",
                                  [(2380, repay), (1930, -repay)])
                    self.overdraft_drawn -= repay
        self.m.secret.setdefault("max_overdraft_drawn", "0")
        if self.overdraft_drawn > Decimal(self.m.secret["max_overdraft_drawn"]):
            self.m.secret["max_overdraft_drawn"] = str(self.overdraft_drawn)

    # ------------------------------------------------------------ year close
    def close_year(self, ye: date):
        prev_month = add_months(D(ye.year, ye.month, 1), -1)
        mk = month_key(ye)
        # accruals (costs) at year end; reversed next month
        accr = [(5020, 13_500, "El"), (5060, 8_500, "Städning"), (6991, 15_000, "Juridik"),
                (5800, 26_000, "Resor")]
        rows = [(acc, M(amt), ) for acc, amt, _ in accr] + [(2990, -M(sum(a for _, a, _ in accr)))]
        self.led.post("E", ye, f"Upplupna kostnader bokslut {ye.year}", rows)
        # revenue accrual FY25: FS-Intranät final invoice (issued after period end)
        if ye == D(2025, 9, 30):
            self.led.post("E", ye, "Upplupen intäkt FS-Intranät slutfaktura",
                          [(1790, M(240_000)), (3011, -M(240_000))])
        # reversal next month (first day)
        nxt = add_months(ye, 1)
        self.led.post("E", D(nxt.year, nxt.month, 1), f"Återföring periodiseringar {ye.year}",
                      [(2990, M(sum(a for _, a, _ in accr)))] +
                      [(acc, -M(amt)) for acc, amt, _ in accr])
        if ye == D(2025, 9, 30):
            self.led.post("E", D(2025, 10, 10), "Återföring upplupen intäkt FS-Intranät",
                          [(3011, M(240_000)), (1790, -M(240_000))])
        # bad debt write-off (Sjöstadens Bryggeri) at FY26 close? No: at 2025-12-31 (event)
        if ye == D(2026, 9, 30):
            # write-off happened 2025-12-31 inside year; nothing extra
            pass
        # tax (with loss carryforward from FY2025)
        result_accounts = [n for n, (nm, k) in ACCOUNTS.items() if k == "I"]
        taxable = M(-sum(self.led.balance(a) for a in result_accounts))  # credit balances negative
        if ye.year == 2025:
            self.loss_cf = max(-taxable, M(0))
        else:
            taxable = max(taxable - getattr(self, "loss_cf", M(0)), M(0))
        taxable = max(taxable, M(0))
        tax = M((taxable * pct(config.TAX["corporate_tax_pct"])).to_integral_value(
            rounding="ROUND_FLOOR") // 100 * 100)
        self.led.post("E", ye, f"Årets skatt {ye.year}", [(8910, tax), (2510, -tax)])
        # close result accounts -> 2099 -> 2091
        net = M(0)
        rows = []
        for a in result_accounts:
            bal = self.led.balance(a)
            if bal != 0:
                rows.append((a, -bal))
                net += bal
        if rows:
            rows.append((2099, net))
            self.led.post("E", ye, f"Resultatöverföring {ye.year}", rows)
        bal2099 = self.led.balance(2099)
        if bal2099 != 0:
            self.led.post("E", ye, f"Överföring till balanserat resultat {ye.year}",
                          [(2099, -bal2099), (2091, bal2099)])
        self.m.secret[f"tax_{ye.year}"] = {"taxable": str(taxable), "tax": str(tax)}
        fy_key = "FY2025" if ye.year == 2025 else "FY2026"
        prelim_paid = M(12 * (25_000 if ye.year == 2025 else 30_000))
        self.m.secret[f"tax_{fy_key}"] = {
            "taxable": str(taxable), "tax": str(tax),
            "prelim_paid": str(prelim_paid),
            "payable": str(max(tax - prelim_paid - (M(300_000) if ye.year == 2026 else M(0)), M(0))),
            "loss_carryforward_used": str(getattr(self, "loss_cf", M(0))) if ye.year == 2026 else "0.00",
        }
        self.m.secret[f"net_result_{ye.year}"] = str(-net - tax)
