"""Receipt layout, PDF output, reprint marking (receipt printing to PDF needs no printer)."""
import os
from datetime import datetime
from decimal import Decimal as D

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from services.receipt_service import CHARS_PER_LINE, build_receipt, sample_receipt  # noqa: E402
from services.settings_service import StoreSettings  # noqa: E402

STORE = StoreSettings(store_name="Sample Corner Store", currency_symbol="₱",
                      receipt_footer="Thank you for shopping!", store_address="123 Rizal St, Quezon City",
                      store_phone="0917 123 4567", tax_id="", costing_method="WEIGHTED_AVERAGE",
                      receipt_note="No returns after 7 days")


def detail():
    return {
        "sale": {"sale_no": "261010-0007", "created_at": datetime(2026, 10, 10, 14, 5),
                 "cashier": "Ana Reyes", "subtotal": D("259.00"), "line_discount": D("8.50"),
                 "sale_discount": D("50.10"), "sale_discount_reason": "Senior citizen",
                 "total": D("200.40"), "change_given": D("299.60"), "receipt_prints": 0},
        "lines": [
            {"name": "Coke Mismo 290ml", "quantity": D("2.000"), "unit_price": D("20.00"),
             "gross_amount": D("40.00"), "line_discount": D("0"), "discount_reason": None},
            {"name": "Pancit Canton Original Flavor Family Pack 6 x 60g", "quantity": D("5.000"),
             "unit_price": D("17.00"), "gross_amount": D("85.00"), "line_discount": D("8.50"),
             "discount_reason": "Promo"},
            {"name": "Rice (Dinorado)", "quantity": D("2.500"), "unit_price": D("53.60"),
             "gross_amount": D("134.00"), "line_discount": D("0"), "discount_reason": None}],
        "payments": [{"method": "Cash", "tendered": D("500.00"), "reference": None}],
    }


@pytest.mark.parametrize("width", [58, 80])
def test_layout_fits_paper(width):
    r = build_receipt(detail(), STORE, width_mm=width)
    w = CHARS_PER_LINE[width]
    assert all(len(l.text) <= w for l in r.lines), [l.text for l in r.lines if len(l.text) > w]
    text = r.plain_text()
    for needle in ("SAMPLE CORNER STORE", "261010-0007", "Ana Reyes", "Coke Mismo 290ml",
                   "2.5 x 53.60", "Less: Promo", "Less: Senior citizen", "₱200.40", "299.60",
                   "Thank you for shopping!", "No returns after 7 days"):
        assert needle in text, needle
    total_line = next(l for l in r.lines if l.text.startswith("TOTAL"))
    assert total_line.bold and total_line.text.endswith("₱200.40") and len(total_line.text) == w
    assert "REPRINT" not in text


def test_reprint_marker_and_sample():
    assert "*** REPRINT ***" in build_receipt(detail(), STORE, reprint=True).plain_text()
    t = sample_receipt(STORE, 80)
    assert t.lines[1].text == "1234567890" * 4 + "12"   # 42-character ruler


def test_pdf_output_is_receipt_sized(tmp_path):
    from PySide6.QtWidgets import QApplication
    from ui.printing import save_receipt_pdf
    QApplication.instance() or QApplication([])
    path = tmp_path / "r.pdf"
    save_receipt_pdf(build_receipt(detail(), STORE, width_mm=58), str(path))
    from PySide6.QtPdf import QPdfDocument               # Qt's own reader: no external tools
    doc = QPdfDocument()
    doc.load(str(path))
    text = doc.getAllText(0).text()
    assert "261010-0007" in text and "TOTAL" in text and "Thank you" in text
    w_pt = doc.pagePointSize(0).width()
    assert abs(w_pt / 72 * 25.4 - 58) < 1.0, w_pt        # 58 mm wide paper
    assert doc.pageCount() == 1                          # one continuous receipt
    doc.close()


def test_missing_printer_gives_clear_message():
    from PySide6.QtWidgets import QApplication
    from services.errors import ServiceError
    from ui.printing import print_receipt
    QApplication.instance() or QApplication([])
    r = build_receipt(detail(), STORE)
    with pytest.raises(ServiceError, match="No receipt printer"):
        print_receipt(r, "")
    with pytest.raises(ServiceError, match="was not found"):
        print_receipt(r, "Imaginary Printer 9000")


@pytest.mark.integration
def test_first_print_then_reprint_is_marked_and_audited(fresh_services):
    from models.cart import Cart
    from services.product_service import ProductInput
    from services.sale_service import PaymentInput
    s = fresh_services
    admin = s.auth.create_first_admin("owner", "Owner", "Owner-Pass-1")
    unit = next(u.id for u in s.catalog.list_units(admin) if u.code == "pc")
    pid = s.products.create(admin, ProductInput(name="Soap", unit_id=unit, selling_price="36"))
    cart = Cart()
    cart.add(s.products.get(admin, pid), "1")
    cash = next(m.id for m in s.sales.payment_methods(admin) if m.is_cash)
    s.settings.update(admin, {"allow_negative_stock": "1"})
    s.shifts.open_shift(admin, "0")
    sale = s.sales.complete_sale(admin, cart, [PaymentInput(cash, "50")])

    first = s.receipts.for_sale(admin, sale.sale_id)
    assert not first.is_reprint and "Soap" in first.plain_text()
    s.receipts.mark_printed(admin, sale.sale_id, sale.sale_no, first.is_reprint, "POS-58")
    again = s.receipts.for_sale(admin, sale.sale_id)
    assert again.is_reprint and "REPRINT" in again.plain_text()
    s.receipts.mark_printed(admin, sale.sale_id, sale.sale_no, again.is_reprint, "POS-58")
    assert [r["action"] for r in s.audit.search(admin, text="reprint")] == ["receipt.reprinted"]

    upd = s.settings.update(admin, {"receipt_printer": "POS-58  Printer", "receipt_width_mm": "80",
                                    "receipt_auto_print": "0"})
    assert upd.receipt_printer == "POS-58  Printer" and upd.receipt_width_mm == 80
    assert not upd.receipt_auto_print
    from services.errors import ValidationError
    with pytest.raises(ValidationError):
        s.settings.update(admin, {"receipt_width_mm": "76"})
