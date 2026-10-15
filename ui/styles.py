"""One place for colors and the Qt style sheet so every screen looks the same."""

from config.settings import resource_path

_ARROW = resource_path("resources/icons/chevron-down.svg").as_posix()

COLORS = {
    "bg": "#F4F5F7",
    "surface": "#FFFFFF",
    "text": "#1C2430",
    "muted": "#5F6B7A",
    "primary": "#1E6B52",
    "primary_hover": "#17573F",
    "primary_soft": "#E3F1EB",
    "danger": "#B42318",
    "danger_soft": "#FDECEA",
    "warning": "#9A6700",
    "border": "#D9DEE4",
    "sidebar": "#123A2E",
    "sidebar_text": "#CFE3DA",
    "sidebar_active": "#1E6B52",
}

C = COLORS

APP_STYLESHEET = f"""
QWidget {{
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 11pt;
    color: {C['text']};
}}
QMainWindow, QDialog, QWidget#Page, QWidget#LoginBackground {{ background: {C['bg']}; }}
QFrame#Card {{
    background: {C['surface']};
    border: 1px solid {C['border']};
    border-radius: 10px;
}}
QLabel#Title {{ font-size: 18pt; font-weight: 600; }}
QLabel#PageTitle {{ font-size: 16pt; font-weight: 600; }}
QLabel#SectionTitle {{ font-size: 12pt; font-weight: 600; }}
QLabel#Muted {{ color: {C['muted']}; }}
QLabel#StatValue {{ font-size: 14pt; font-weight: 600; }}
QLabel#StatusOk {{ color: {C['primary']}; font-weight: 600; }}
QLabel#StatusError, QLabel#ErrorText {{ color: {C['danger']}; font-weight: 600; }}
QLabel#ErrorBox {{
    color: {C['danger']}; background: {C['danger_soft']};
    border-radius: 6px; padding: 8px 10px;
}}
QLabel#Chip {{
    background: {C['primary_soft']}; color: {C['primary']};
    border-radius: 10px; padding: 2px 10px; font-size: 9.5pt; font-weight: 600;
}}

QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
    background: {C['surface']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 6px 8px;
    min-height: 22px;
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {C['primary']}; padding: 5px 7px;
}}
QLineEdit:read-only {{ background: {C['bg']}; color: {C['muted']}; }}

QPushButton {{
    background: {C['surface']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 7px 16px;
}}
QPushButton:hover {{ border-color: {C['primary']}; }}
QPushButton:disabled {{ color: #A0A8B3; background: #F0F1F3; }}
QPushButton:checked {{
    background: {C['primary_soft']}; border: 2px solid {C['primary']};
    color: {C['primary']}; font-weight: 600;
}}
QPushButton#Quick {{ padding: 6px 4px; min-width: 52px; }}
QPushButton#Primary {{ background: {C['primary']}; color: white; border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {C['primary_hover']}; }}
QPushButton#Primary:disabled {{ background: #9DB9AE; }}
QPushButton#Danger {{ color: {C['danger']}; }}
QPushButton#Link {{ border: none; background: transparent; color: {C['primary']}; padding: 4px 6px; }}
QPushButton#Link:hover {{ text-decoration: underline; }}

QTableWidget {{
    background: {C['surface']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    gridline-color: #EEF0F3;
    selection-background-color: {C['primary_soft']};
    selection-color: {C['text']};
}}
QTableWidget::item {{ padding: 4px 8px; }}
QComboBox::drop-down, QDateEdit::drop-down {{
    border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right;
}}
QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url("{_ARROW}"); width: 12px; height: 12px; }}
QHeaderView::section {{
    background: #F8F9FA; border: none; border-bottom: 1px solid {C['border']};
    padding: 8px; font-weight: 600; color: {C['muted']};
}}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; border: none; border-bottom: 2px solid transparent;
    padding: 8px 18px; color: {C['muted']}; font-weight: 600;
}}
QTabBar::tab:selected {{ color: {C['primary']}; border-bottom: 2px solid {C['primary']}; }}
QTabBar::tab:hover {{ color: {C['text']}; }}
QCheckBox {{ spacing: 8px; }}

QWidget#Sidebar {{ background: {C['sidebar']}; }}
QLabel#SidebarTitle {{ color: white; font-size: 13pt; font-weight: 600; }}
QLabel#SidebarSub {{ color: {C['sidebar_text']}; font-size: 9.5pt; }}
QPushButton#NavButton {{
    color: {C['sidebar_text']}; background: transparent; border: none;
    text-align: left; padding: 10px 16px; border-radius: 6px; font-size: 11pt;
}}
QPushButton#NavButton:hover {{ background: #1A4A3B; color: white; }}
QPushButton#NavButton:checked {{ background: {C['sidebar_active']}; color: white; font-weight: 600; }}
QWidget#TopBar {{ background: {C['surface']}; border-bottom: 1px solid {C['border']}; }}
"""
