"""SL583 peptide-vial label sheet engine for The Peptide Wizard.

Ported verbatim from the local `label_printer` desktop app (calibrated 2026-06-24
against Ben's real printer) so PDFs generated here print PIXEL-IDENTICAL on the same
SheetLabels.com SL583 stock: 48 labels per US-Letter sheet, 1.75" x 0.75", 4 across
x 12 down. This module is self-contained (no DB, no network) — the Flask app hands it
a list of ready-to-print label dicts and gets back PDF bytes.

Label content (matches the current wizard artwork `assets/pw_base.png`, which has the
logo / "THE PEPTIDE WIZARD" / "Lyophilized Powder" / "RESEARCH USE ONLY" / orb baked
in; we stamp the four dynamic fields on top):
    - peptide NAME     (horizontal, bold, e.g. "SELANK")
    - STRENGTH         (horizontal, bold, e.g. "10MG")
    - LOT #            (rotated 90 deg)
    - EXP              (rotated 90 deg, MM/DD/YYYY)

Public API:
    parse_name_strength(product_name) -> (name, strength)
    compute_lot(sku, po_number)       -> "SK10-2026-0012"
    compute_exp(received_iso)         -> "MM/DD/YYYY"  (received + 2 years)
    build_label_pdf(labels)           -> (bytes, sheets)   labels: [{name,strength,lot,exp,count}]
"""
import io
import os
import re
from datetime import date, datetime

# ── SL583 sheet geometry (points; 72 pt = 1 inch; reportlab origin = bottom-left) ──
IN = 72.0
PAGE_W = 8.5 * IN            # 612 pt
PAGE_H = 11.0 * IN           # 792 pt
LABEL_W = 1.75 * IN          # 126 pt
LABEL_H = 0.75 * IN          # 54 pt
COLS, ROWS = 4, 12
PER_SHEET = COLS * ROWS      # 48

# Calibrated 2026-06-24 from a real test print on Ben's printer (see label_printer/sl583.py)
MARGIN_LEFT = 54.0           # 40.5 + 3/16"
MARGIN_TOP = 27.25           # 36.25 - 1/8"
COL_PITCH = 135.0            # 1.875"
ROW_PITCH = 62.75            # 60.5 + 1/32"
ART_MARGIN_X = 4.0           # inset so artwork sits inside the die-cut
ART_MARGIN_Y = 3.0

# ── Dynamic-text stamp layout (points, relative to a cell's bottom-left) ──
# From the label_printer product rows — the same for every SKU because it keys off
# the artwork, not the product. Tune here if the text ever drifts on the artwork.
NAME_X, NAME_Y, NAME_FS = 30.0, 23.5, 6.0
STRENGTH_X, STRENGTH_Y, STRENGTH_FS = 30.0, 18.5, 6.5
LOT_X, LOT_Y = 60.0, 5.0
EXP_X, EXP_Y = 67.0, 5.0
TEXT_ROT = 90.0
LOTEXP_FS = 4.0
NAME_MAX_W = 52.0            # shrink the name font if it would overflow this width

_ART_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "pw_base.png")
_art_reader = None           # cached reportlab ImageReader for the base artwork


def _cell_rect(index):
    """(x, y, w, h) of cell `index` (0..47), bottom-left origin, filling L->R, T->B."""
    col = index % COLS
    row = index // COLS
    x_left = MARGIN_LEFT + col * COL_PITCH
    y_top = PAGE_H - MARGIN_TOP - row * ROW_PITCH
    return (x_left, y_top - LABEL_H, LABEL_W, LABEL_H)


def sheets_needed(n):
    return 0 if n <= 0 else (n + PER_SHEET - 1) // PER_SHEET


# ── Field helpers ─────────────────────────────────────────────────────────────
def parse_name_strength(product_name):
    """PW product names embed the strength: "Selank (10mg/10vials)" ->
    ("Selank", "10MG"). Falls back gracefully if the pattern is absent."""
    product_name = (product_name or "").strip()
    strength = ""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(mg|mcg|iu)\b", product_name, re.I)
    if m:
        strength = f"{m.group(1)}{m.group(2).upper()}"
    name = re.split(r"\s*\(", product_name, 1)[0].strip()
    # Catalog names like "KPV - LYSINE-PROLINE-VALINE" -> "KPV" (only a SPACED dash;
    # leaves hyphenated names like "CJC-1295 DAC" / "GHK-CU" intact).
    name = re.split(r"\s+-\s+", name, 1)[0].strip()
    return name, strength


def compute_lot(sku, po_number):
    """LOT # = SKU + PO number with the leading "PO-" dropped.
    e.g. sku="SK10", po_number="PO-2026-0012" -> "SK10-2026-0012"."""
    po = (po_number or "").strip()
    if po.upper().startswith("PO-"):
        po = po[3:]
    elif po.upper().startswith("PO"):
        po = po[2:]
    return f"{(sku or '').strip()}-{po}"


def compute_exp(received_iso):
    """received date (ISO or ISO timestamp) + 2 years -> MM/DD/YYYY. Leap-safe.
    Empty / unparseable -> today + 2 years."""
    d = None
    s = (received_iso or "").strip()
    if s:
        try:
            d = datetime.fromisoformat(s.replace("Z", "")).date()
        except ValueError:
            try:
                d = datetime.strptime(s[:10], "%Y-%m-%d").date()
            except ValueError:
                d = None
    if d is None:
        d = date.today()
    # +2 years, leap-safe (Feb 29 -> Feb 28)
    try:
        exp = d.replace(year=d.year + 2)
    except ValueError:
        exp = d.replace(month=2, day=28, year=d.year + 2)
    return exp.strftime("%m/%d/%Y")


# ── Rendering ─────────────────────────────────────────────────────────────────
def _get_art_reader():
    global _art_reader
    if _art_reader is None:
        from reportlab.lib.utils import ImageReader
        try:
            from PIL import Image  # reportlab embeds PNG via PIL
            _art_reader = ImageReader(Image.open(_ART_PATH).convert("RGB"))
        except Exception:
            _art_reader = ImageReader(_ART_PATH)
    return _art_reader


def _stamp(c, cx, cy, name, strength, lot, exp):
    """Stamp the four dynamic fields over a cell whose bottom-left is (cx, cy)."""
    if name:
        fs = NAME_FS
        while fs > 3.0 and c.stringWidth(name, "Helvetica-Bold", fs) > NAME_MAX_W:
            fs -= 0.25
        c.setFont("Helvetica-Bold", fs)
        c.drawCentredString(cx + NAME_X, cy + NAME_Y, name)
    if strength:
        c.setFont("Helvetica-Bold", STRENGTH_FS)
        c.drawCentredString(cx + STRENGTH_X, cy + STRENGTH_Y, strength)
    c.setFont("Helvetica", LOTEXP_FS)
    if lot:
        c.saveState()
        c.translate(cx + LOT_X, cy + LOT_Y)
        c.rotate(TEXT_ROT)
        c.drawString(0, 0, f"LOT #: {lot}")
        c.restoreState()
    if exp:
        c.saveState()
        c.translate(cx + EXP_X, cy + EXP_Y)
        c.rotate(TEXT_ROT)
        c.drawString(0, 0, f"EXP: {exp}")
        c.restoreState()


def build_label_pdf(labels):
    """Tile `labels` onto SL583 sheets and stamp each. Returns (pdf_bytes, sheets).

    labels: [{"name","strength","lot","exp","count"}] — one physical label printed
    `count` times, in list order, left->right / top->bottom, new sheet every 48.
    Returns (None, 0) if reportlab is unavailable.
    """
    try:
        from reportlab.pdfgen import canvas
    except ImportError:
        return None, 0

    # Expand to one entry per physical label
    cells = []
    for lb in labels:
        n = max(0, int(lb.get("count", 0) or 0))
        for _ in range(n):
            cells.append(lb)
    if not cells:
        return None, 0

    art = _get_art_reader()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    for i, lb in enumerate(cells):
        slot = i % PER_SHEET
        if i > 0 and slot == 0:
            c.showPage()
        x, y, w, h = _cell_rect(slot)
        c.drawImage(art, x + ART_MARGIN_X, y + ART_MARGIN_Y,
                    width=w - 2 * ART_MARGIN_X, height=h - 2 * ART_MARGIN_Y,
                    preserveAspectRatio=False, mask="auto")
        _stamp(c, x, y, lb.get("name", ""), lb.get("strength", ""),
               lb.get("lot", ""), lb.get("exp", ""))
    c.showPage()
    c.save()
    return buf.getvalue(), sheets_needed(len(cells))


# ── CLI smoke test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    demo = [
        {"name": "SELANK", "strength": "10MG", "lot": "SK10-2026-0012", "exp": "07/18/2028", "count": 12},
        {"name": "MOTS-C", "strength": "10MG", "lot": "MS10-2026-0012", "exp": "07/18/2028", "count": 42},
        {"name": "KPV",    "strength": "10MG", "lot": "KPV10-2026-0012", "exp": "07/18/2028", "count": 22},
    ]
    pdf, sheets = build_label_pdf(demo)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "label_engine_demo.pdf")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(pdf)
    print(f"wrote {out} — {len(demo)} SKUs, {sheets} sheet(s)")
