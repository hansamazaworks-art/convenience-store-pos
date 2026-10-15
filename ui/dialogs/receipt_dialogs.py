"""Receipt preview and the shared 'print this sale's receipt' action."""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QDialog, QFileDialog, QTextEdit, QVBoxLayout, QWidget

from models.user import Session
from services.container import Services
from services.receipt_service import CHARS_PER_LINE, Receipt
from ui.printing import print_receipt, save_receipt_pdf
from ui.widgets.common import button, button_row, info, label, run, show_error


def receipt_html(receipt: Receipt) -> str:
    w = CHARS_PER_LINE[receipt.width_mm]
    rows = []
    for line in receipt.lines:
        text = line.text.center(w).rstrip() if line.center else line.text
        text = html.escape(text) or "&nbsp;"
        rows.append(f"<b>{text}</b>" if line.bold else text)
    return ("<pre style='font-family: Consolas, \"Courier New\", monospace; font-size: 10.5pt; "
            "margin: 0;'>" + "\n".join(rows) + "</pre>")


class ReceiptPreviewDialog(QDialog):
    """Shows the receipt exactly as it will print, with Print and Save as PDF."""

    def __init__(self, receipt: Receipt, parent: QWidget | None = None, on_print=None) -> None:
        super().__init__(parent)
        self.receipt = receipt
        self.on_print = on_print
        self.setWindowTitle(f"Receipt {receipt.sale_no}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.addWidget(label(f"Receipt preview ({receipt.width_mm} mm paper)", "SectionTitle"))
        paper = QTextEdit(readOnly=True)
        paper.setHtml(receipt_html(receipt))
        paper.setStyleSheet("QTextEdit { background: white; border: 1px solid #D9DEE4; "
                            "border-radius: 4px; padding: 10px; }")
        f = QFont("Consolas")
        f.setFamilies(["Consolas", "Courier New", "DejaVu Sans Mono"])
        f.setPointSizeF(10.5)
        char_w = QFontMetrics(f).horizontalAdvance("0")
        paper.setFixedWidth(int(CHARS_PER_LINE[receipt.width_mm] * char_w) + 60)
        paper.setMinimumHeight(460)
        lay.addWidget(paper, 1)
        btns = []
        if on_print:
            btns.append(button("Print", self._print, "Primary", "Ctrl+P"))
        btns.append(button("Save as PDF", self._pdf))
        btns.append(button("Close", self.accept))
        lay.addLayout(button_row(*btns))

    def _print(self) -> None:
        if self.on_print and self.on_print():
            self.accept()

    def _pdf(self) -> None:
        default = str(Path.home() / "Documents" / f"Receipt {self.receipt.sale_no}.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Save receipt as PDF", default, "PDF files (*.pdf)")
        if not path:
            return
        ok, _ = run(self, save_receipt_pdf, self.receipt, path)
        if ok:
            info(self, "Saved", f"Receipt saved to:\n{path}")


def print_sale_receipt(parent: QWidget, services: Services, session: Session, sale_id: int) -> bool:
    """Print the receipt of a saved sale. Returns True if it was sent to the printer.
    A failed print never affects the sale itself."""
    ok, receipt = run(parent, services.receipts.for_sale, session, sale_id)
    if not ok:
        return False
    printer = services.settings.get().receipt_printer
    try:
        print_receipt(receipt, printer)
    except Exception as exc:  # noqa: BLE001
        show_error(parent, exc)
        return False
    run(parent, services.receipts.mark_printed, session, sale_id, receipt.sale_no,
        receipt.is_reprint, printer)
    return True


def show_sale_receipt(parent: QWidget, services: Services, session: Session, sale_id: int) -> None:
    """Preview with a Print button (used for reprints from Sales history)."""
    ok, receipt = run(parent, services.receipts.preview, session, sale_id)
    if ok:
        can_print = session.can("pos.reprint") or session.can("pos.sell")
        ReceiptPreviewDialog(
            receipt, parent,
            on_print=(lambda: print_sale_receipt(parent, services, session, sale_id)) if can_print else None,
        ).exec()
