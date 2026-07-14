"""Build a one-page PDF spec sheet for a wall-actuator configuration.

Pure fpdf2: it takes already-computed text rows and pre-rendered PNG images, so
it has no plotly/kaleido/Streamlit dependency and is trivial to unit-test. The
caller (app.py) gathers the numbers and renders the figures to PNG.
"""
import io

from fpdf import FPDF
from fpdf.enums import XPos, YPos

# fpdf2's core fonts are latin-1 only; map the few unicode glyphs the app uses.
_SUBS = {"×": "x", "→": "->", "°": " deg", "–": "-", "—": "-", "≤": "<=",
         "≥": ">=", "√": "sqrt", "·": "-", "±": "+/-", "≈": "~", "θ": "theta"}

# multi_cell in fpdf2 2.8 does not return x to the left margin by default; make
# the "next line, back to the left margin" behaviour explicit.
_NL = dict(new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _ascii(s):
    s = str(s)
    for a, b in _SUBS.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def build_spec_pdf(title, subtitle, tables, images=None, notes=None):
    """Return PDF bytes for a design spec sheet.

    title, subtitle : header strings.
    tables  : list of (heading, [(label, value), ...]).
    images  : list of (caption, png_bytes) rendered full width, in order.
    notes   : list of caveat strings printed small at the end.
    """
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_title(_ascii(title))
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 8, text=_ascii(title), **_NL)
    if subtitle:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(110, 110, 110)
        pdf.multi_cell(0, 5, text=_ascii(subtitle), **_NL)
        pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    for heading, rows in tables:
        pdf.set_font("Helvetica", "B", 11)
        pdf.multi_cell(0, 6, text=_ascii(heading), **_NL)
        for label, value in rows:
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(72, 5.5, text=_ascii(label), new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 5.5, text=_ascii(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)

    for caption, png in (images or []):
        if caption:
            pdf.set_font("Helvetica", "B", 10)
            pdf.multi_cell(0, 6, text=_ascii(caption), **_NL)
        pdf.image(io.BytesIO(png), w=180)
        pdf.ln(3)

    if notes:
        pdf.ln(1)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(110, 110, 110)
        for n in notes:
            pdf.multi_cell(0, 4, text=_ascii("- " + n), **_NL)
        pdf.set_text_color(0, 0, 0)

    return bytes(pdf.output())
