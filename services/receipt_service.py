"""Builds receipt text for thermal printers (58 mm = 32 characters, 80 mm = 42).

The same lines are used for the on-screen preview, the printer and PDF copies,
so what the cashier sees is exactly what prints.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass
from decimal import Decimal

from database.connection import Database
from models.user import Session
from repositories.sale_repository import SaleRepository
from services.audit_service import AuditService
from services.sale_service import SaleService
from services.settings_service import SettingsService, StoreSettings

CHARS_PER_LINE = {58: 32, 80: 42}


@dataclass(frozen=True)
class ReceiptLine:
    text: str
    bold: bool = False
    center: bool = False


@dataclass(frozen=True)
class Receipt:
    lines: list[ReceiptLine]
    width_mm: int
    sale_no: str
    is_reprint: bool

    def plain_text(self) -> str:
        w = CHARS_PER_LINE[self.width_mm]
        return "\n".join(l.text.center(w).rstrip() if l.center else l.text for l in self.lines)


def _num(v: Decimal) -> str:
    return f"{Decimal(v):,.2f}"


def _qty(v: Decimal) -> str:
    return f"{Decimal(v).normalize():f}"


def _lr(left: str, right: str, width: int) -> str:
    """Left text and right-aligned amount on one line (left is cut if needed)."""
    space = width - len(right) - 1
    if len(left) > space:
        left = left[:max(0, space)]
    return left + " " * (width - len(left) - len(right)) + right


def build_receipt(detail: dict, store: StoreSettings, *, reprint: bool = False,
                  width_mm: int | None = None) -> Receipt:
    width_mm = width_mm or store.receipt_width_mm
    w = CHARS_PER_LINE.get(width_mm, 32)
    s, lines, pays = detail["sale"], detail["lines"], detail["payments"]
    out: list[ReceiptLine] = []
    add = lambda text="", **kw: out.append(ReceiptLine(text, **kw))  # noqa: E731
    rule = lambda ch="-": add(ch * w)  # noqa: E731

    def wrapped(text: str, center: bool = False, bold: bool = False, indent: str = "") -> None:
        for part in textwrap.wrap(text, w, subsequent_indent=indent) or [""]:
            add(part, center=center, bold=bold)

    # ---- header
    wrapped(store.store_name.upper(), center=True, bold=True)
    for extra in (store.store_address, store.store_phone and f"Tel {store.store_phone}",
                  store.tax_id and f"TIN/ID {store.tax_id}"):
        if extra:
            wrapped(extra, center=True)
    if reprint:
        add()
        add("*** REPRINT ***", center=True, bold=True)
    rule()
    add(f"Sale #: {s['sale_no']}")
    add(f"Date  : {s['created_at'].strftime('%d %b %Y %H:%M')}")
    add(f"Cashier: {s['cashier']}"[:w])
    rule()

    # ---- items
    for l in lines:
        wrapped(l["name"], indent="  ")
        add(_lr(f"  {_qty(l['quantity'])} x {_num(l['unit_price'])}", _num(l["gross_amount"]), w))
        if l["line_discount"]:
            add(_lr(f"  Less: {l['discount_reason'] or 'discount'}", f"-{_num(l['line_discount'])}", w))
    rule()

    # ---- totals
    add(_lr("Subtotal", _num(s["subtotal"]), w))
    if s["line_discount"]:
        add(_lr("Item discounts", f"-{_num(s['line_discount'])}", w))
    if s["sale_discount"]:
        add(_lr(f"Less: {s['sale_discount_reason'] or 'discount'}", f"-{_num(s['sale_discount'])}", w))
    add(_lr("TOTAL", f"{store.currency_symbol}{_num(s['total'])}", w), bold=True)
    rule()
    for p in pays:
        add(_lr(p["method"] if p["method"] else "Payment", _num(p["tendered"]), w))
        if p["reference"]:
            add(f"  Ref: {p['reference']}"[:w])
    add(_lr("Change", _num(s["change_given"]), w), bold=True)
    rule()
    count = sum(Decimal(l["quantity"]) for l in lines)
    add(_lr(f"Items: {_qty(count)}", f"Lines: {len(lines)}", w))

    # ---- footer
    if store.receipt_note:
        add()
        wrapped(store.receipt_note, center=True)
    if store.receipt_footer:
        add()
        wrapped(store.receipt_footer, center=True)
    add()
    return Receipt(out, width_mm, s["sale_no"], reprint)


def sample_receipt(store: StoreSettings, width_mm: int | None = None) -> Receipt:
    """A sample receipt for checking the printer and paper width."""
    from datetime import datetime
    w = CHARS_PER_LINE.get(width_mm or store.receipt_width_mm, 32)
    detail = {
        "sale": {"sale_no": "TEST-PRINT", "created_at": datetime.now(), "cashier": "Printer test",
                 "subtotal": Decimal("57.00"), "line_discount": Decimal("0"),
                 "sale_discount": Decimal("0"), "sale_discount_reason": None,
                 "total": Decimal("57.00"), "change_given": Decimal("43.00")},
        "lines": [{"name": "Sample item with a long name to check wrapping", "quantity": Decimal("2"),
                   "unit_price": Decimal("20.00"), "gross_amount": Decimal("40.00"),
                   "line_discount": Decimal("0"), "discount_reason": None},
                  {"name": "Another item", "quantity": Decimal("1"), "unit_price": Decimal("17.00"),
                   "gross_amount": Decimal("17.00"), "line_discount": Decimal("0"),
                   "discount_reason": None}],
        "payments": [{"method": "Cash", "tendered": Decimal("100.00"), "reference": None}],
    }
    r = build_receipt(detail, store, width_mm=width_mm)
    ruler = "".join(str(i % 10) for i in range(1, w + 1))
    return Receipt([ReceiptLine("PRINTER TEST", bold=True, center=True), ReceiptLine(ruler)]
                   + r.lines, r.width_mm, "TEST", False)


def build_shift_report(summary, movements: list[dict], store: StoreSettings) -> Receipt:
    """End-of-shift slip for the receipt printer (services.shift_service.ShiftSummary)."""
    w = CHARS_PER_LINE.get(store.receipt_width_mm, 32)
    sh = summary.shift
    out: list[ReceiptLine] = []
    add = lambda text="", **kw: out.append(ReceiptLine(text, **kw))  # noqa: E731
    add(store.store_name.upper()[:w], center=True, bold=True)
    add("SHIFT REPORT", center=True, bold=True)
    add("-" * w)
    add(f"Shift  : {sh['shift_no']}")
    add(f"Cashier: {sh['user_name']}"[:w])
    add(f"Opened : {sh['opened_at'].strftime('%d %b %Y %H:%M')}")
    if sh.get("closed_at"):
        add(f"Closed : {sh['closed_at'].strftime('%d %b %Y %H:%M')}")
    add("-" * w)
    add(_lr(f"Sales ({summary.sales_count})", _num(summary.sales_total), w))
    for p in summary.payments:
        add(_lr(f"  {p['name']}", _num(p["amount"]), w))
    add("-" * w)
    add("CASH DRAWER", bold=True)
    add(_lr("Starting cash", _num(sh["opening_float"]), w))
    add(_lr("+ Cash sales", _num(summary.cash_sales), w))
    for m in movements:
        sign = "+" if m["kind"] in ("cash_in", "expense_void") else "-"
        add(_lr(f"{sign} {m['label']}", _num(m["amount"]), w))
        if m.get("reason"):
            add(f"   {m['reason']}"[:w])
    if summary.expected_cash is not None:
        add(_lr("Expected cash", _num(summary.expected_cash), w), bold=True)
    if sh.get("counted_cash") is not None:
        add(_lr("Counted cash", _num(sh["counted_cash"]), w), bold=True)
        diff = Decimal(sh["difference"])
        word = "OVER" if diff > 0 else "SHORT" if diff < 0 else "Difference"
        add(_lr(word, _num(diff), w), bold=True)
    if sh.get("close_note"):
        add(f"Note: {sh['close_note']}"[:w])
    add("-" * w)
    add()
    add("Cashier: ______________")
    add()
    add("Checked: ______________")
    add()
    return Receipt(out, store.receipt_width_mm, sh["shift_no"], False)


class ReceiptService:
    def __init__(self, db: Database, sales: SaleService, settings: SettingsService,
                 audit: AuditService | None = None) -> None:
        self.db = db
        self.sales = sales
        self.settings = settings
        self.repo = SaleRepository(db)
        self.audit = audit or AuditService(db)

    def for_sale(self, session: Session, sale_id: int) -> Receipt:
        """Receipt for printing. The first print is the original; later ones say REPRINT."""
        detail = self.sales.sale_detail(session, sale_id)   # checks who may see the sale
        reprint = int(detail["sale"].get("receipt_prints") or 0) > 0
        if reprint:
            session.require("pos.reprint", "reprint receipts")
        return build_receipt(detail, self.settings.get(), reprint=reprint)

    def preview(self, session: Session, sale_id: int) -> Receipt:
        """Receipt for looking at on screen (does not count as a print)."""
        detail = self.sales.sale_detail(session, sale_id)
        reprint = int(detail["sale"].get("receipt_prints") or 0) > 0
        return build_receipt(detail, self.settings.get(), reprint=reprint)

    def mark_printed(self, session: Session, sale_id: int, sale_no: str, reprint: bool,
                     printer: str) -> None:
        with self.db.transaction() as cur:
            cur.execute("UPDATE sales SET receipt_prints = receipt_prints + 1 WHERE id = %s", (sale_id,))
            if reprint:
                self.audit.record(cur, "receipt.reprinted", session=session, entity_type="sale",
                                  entity_id=sale_no, details={"printer": printer})
