"""Unit tests for the PDF spec-sheet builder (report.py)."""
import base64

import report

# Smallest valid 1x1 PNG, so the image path is exercised without kaleido.
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def test_build_spec_pdf_returns_valid_pdf():
    tables = [("Setup", [("Container", "Standard"), ("Mass", "500 kg")]),
              ("Geometry", [("a", "0.60 m"), ("b", "1.80 m")])]
    pdf = report.build_spec_pdf("Design Report", "subtitle", tables)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 400


def test_build_spec_pdf_sanitizes_unicode():
    # Unicode glyphs must not raise against fpdf2's latin-1 core fonts.
    tables = [("Cylinder theta x deg", [("peak", "12.9 N/kg → 6.5 kN")])]
    pdf = report.build_spec_pdf("Wall — Report", "θ = 45° · ≥1.5×", tables,
                                notes=["Apply ≥1.5× safety.", "√ works too."])
    assert pdf[:4] == b"%PDF"


def test_build_spec_pdf_embeds_image():
    pdf = report.build_spec_pdf("Report", "", [("S", [("k", "v")])],
                                images=[("Side view", _PNG_1x1)])
    assert pdf[:4] == b"%PDF"


def test_ascii_replaces_known_glyphs():
    assert report._ascii("a×b→c°") == "axb->c deg"
    # unmapped non-latin-1 is replaced, never raised
    assert isinstance(report._ascii("emoji 😀 and 汉字"), str)


def test_dual_unit_formatters():
    # metric first, imperial in parentheses; guards the conversion constants
    assert report.dual_len(1.0) == "1.000 m (39.37 in)"
    assert report.dual_force(25000.0) == "25.0 kN (5,620 lbf)"
    assert report.dual_pressure(210.0) == "210 bar (3,046 psi)"
    assert report.dual_bore(40.0) == "40.0 mm (1.57 in)"
    assert report.dual_mass(500.0) == "500 kg (1,102 lb)"
