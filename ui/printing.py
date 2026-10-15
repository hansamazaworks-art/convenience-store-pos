"""Sends receipts to a Windows printer (thermal or normal) or to a PDF file.

We print through the Windows printer driver, so any printer that Windows can
use works - including 58/80 mm thermal printers. Each receipt is one long
page exactly as tall as its text.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from services.errors import ServiceError
from services.receipt_service import CHARS_PER_LINE, Receipt

log = logging.getLogger(__name__)

PRINTABLE_MM = {58: 48.0, 80: 72.0}   # usual printable width of the paper
MARGIN_MM = 2.0
_FONT_FAMILY = "Consolas"             # monospaced, on every Windows PC
_FALLBACK = ["Courier New", "DejaVu Sans Mono", "Monospace"]


def available_printers() -> list[str]:
    return [p.printerName() for p in QPrinterInfo.availablePrinters()]


def default_printer() -> str:
    return QPrinterInfo.defaultPrinter().printerName()


def _font(pt: float, bold: bool = False) -> QFont:
    f = QFont(_FONT_FAMILY)
    f.setFamilies([_FONT_FAMILY, *_FALLBACK])
    f.setStyleHint(QFont.TypeWriter)
    f.setPointSizeF(pt)
    f.setBold(bold)
    return f


def _render(printer: QPrinter, receipt: Receipt) -> None:
    chars = CHARS_PER_LINE[receipt.width_mm]
    width_mm = PRINTABLE_MM[receipt.width_mm]
    # Pick the font size so that `chars` characters fill the printable width.
    probe = _font(10)
    fm = QFontMetricsF(probe, printer)
    char_w = fm.horizontalAdvance("0" * 10) / 10
    dpi = printer.resolution()
    width_px = width_mm / 25.4 * dpi
    pt = max(5.0, min(14.0, 10 * width_px / (char_w * chars) * 0.98))
    normal, bold = _font(pt), _font(pt, True)
    line_h = QFontMetricsF(normal, printer).height() * 1.05

    height_mm = (len(receipt.lines) * line_h) / dpi * 25.4 + 2 * MARGIN_MM + 6
    page = QPageSize(QSizeF(receipt.width_mm, height_mm), QPageSize.Millimeter, "Receipt",
                     QPageSize.ExactMatch)
    printer.setPageLayout(QPageLayout(page, QPageLayout.Portrait,
                                      QMarginsF(MARGIN_MM, MARGIN_MM, MARGIN_MM, MARGIN_MM),
                                      QPageLayout.Millimeter))
    painter = QPainter()
    if not painter.begin(printer):
        raise ServiceError("The printer could not be started. Check that it is switched on, "
                           "has paper, and is chosen correctly in Store settings.")
    try:
        usable_px = (receipt.width_mm - 2 * MARGIN_MM) / 25.4 * dpi
        x0 = max(0.0, (usable_px - width_px) / 2)   # centre the text block on the paper
        y = 0.0
        for line in receipt.lines:
            painter.setFont(bold if line.bold else normal)
            rect = QRectF(x0, y, width_px, line_h)
            align = (Qt.AlignHCenter if line.center else Qt.AlignLeft) | Qt.AlignVCenter
            painter.drawText(rect, int(align), line.text)
            y += line_h
    finally:
        painter.end()


def print_receipt(receipt: Receipt, printer_name: str) -> None:
    if not printer_name:
        raise ServiceError("No receipt printer is chosen yet.\n"
                           "An administrator can choose it in Store settings → Receipt printer.")
    info = QPrinterInfo.printerInfo(printer_name)
    if info.isNull():
        raise ServiceError(f"The printer '{printer_name}' was not found on this computer.\n"
                           "Check it is installed, or choose another one in Store settings.")
    printer = QPrinter(info, QPrinter.HighResolution)
    printer.setDocName(f"Receipt {receipt.sale_no}")
    printer.setFullPage(False)
    _render(printer, receipt)
    log.info("Receipt %s sent to printer %s", receipt.sale_no, printer_name)


def save_receipt_pdf(receipt: Receipt, path: str) -> None:
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(path)
    printer.setDocName(f"Receipt {receipt.sale_no}")
    _render(printer, receipt)
