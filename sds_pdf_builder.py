"""
16-Section SDS PDF Builder — ReportLab Platypus.

Architecture mirrors tds_pdf_builder.py from the TDS Generator project:
  - Same BaseDocTemplate + Frame + PageTemplate + onPage footer pattern
  - Same _section_bar(), _two_col_table(), _hex(), _esc() helper primitives
  - Each SDS section is a discrete build_section_N_*() function

Key difference from TDS: NO ingredient redaction — CAS numbers and
concentrations are fully disclosed as required by OSHA HCS 2012.

Layout: 16 sections flow naturally and fill pages. CondPageBreak before
        each section header prevents orphaned headers without leaving
        large blank gaps; long tables split with repeatRows=1 so the
        header row repeats on every page.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    CondPageBreak,
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from brand_config import BrandConfig
from sds_data_model import SDSDocument, SDSProduct

# ---------------------------------------------------------------------------
# Layout constants (same as tds_pdf_builder.py)
# ---------------------------------------------------------------------------

_MODULE_DIR = Path(__file__).parent

PAGE_W, PAGE_H = A4
MARGIN     = 15 * mm
CONTENT_W  = PAGE_W - 2 * MARGIN

FONT_BODY = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_IT   = "Helvetica-Oblique"


def _resolve_logo(logo_path: str) -> Path:
    p = Path(logo_path)
    return p if p.is_absolute() else _MODULE_DIR / p


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_sds_pdf(doc: SDSDocument, output_path: str | Path,
                  brand: BrandConfig | None = None) -> Path:
    """Build a professional 16-section SDS PDF. Returns the output path."""
    if brand is None:
        brand = BrandConfig()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    styles = _make_styles(brand)
    story  = _build_story(doc, brand, styles)
    _build_doc(story, out, brand, doc)
    return out


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------

def _build_story(doc: SDSDocument, brand: BrandConfig, styles: dict) -> list:
    p = doc.product
    story: list = []

    story += _build_sds_cover_header(p, brand, styles)
    story += build_section_1_identification(p, brand, styles)
    story += build_section_2_hazards(p, brand, styles)
    story += build_section_3_composition(p, brand, styles)
    story += build_section_4_first_aid(p, brand, styles)
    story += build_section_5_firefighting(p, brand, styles)
    story += build_section_6_release(p, brand, styles)
    story += build_section_7_handling(p, brand, styles)
    story += build_section_8_exposure(p, brand, styles)
    story += build_section_9_properties(p, brand, styles)
    story += build_section_10_stability(p, brand, styles)
    story += build_section_11_toxicology(p, brand, styles)
    story += build_section_12_ecology(p, brand, styles)
    story += build_section_13_disposal(p, brand, styles)
    story += build_section_14_transport(p, brand, styles)
    story += build_section_15_regulatory(p, brand, styles)
    story += build_section_16_other(p, brand, styles)

    return story


def _build_doc(story: list, out: Path, brand: BrandConfig,
               sds: SDSDocument) -> None:
    _brand = brand

    def _on_page(canvas, doc):
        canvas.saveState()
        _draw_sds_footer(canvas, doc, _brand, sds)
        canvas.restoreState()

    pdf_doc = BaseDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=20 * mm,
    )
    frame = Frame(MARGIN, 20 * mm, CONTENT_W, PAGE_H - MARGIN - 20 * mm,
                  id="main", leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    template = PageTemplate(id="main", frames=[frame], onPage=_on_page)
    pdf_doc.addPageTemplates([template])
    pdf_doc.build(story)


def _draw_sds_footer(canvas, doc, brand: BrandConfig, sds: SDSDocument) -> None:
    c_accent = _hex(brand.accent)
    y_rule = 17 * mm
    canvas.setStrokeColor(c_accent)
    canvas.setLineWidth(1.5)
    canvas.line(MARGIN, y_rule, PAGE_W - MARGIN, y_rule)

    canvas.setFont(FONT_BODY, 6.5)
    canvas.setFillColor(colors.HexColor("#555555"))

    p = sds.product
    left_text = (
        f"{brand.company_name}  |  "
        f"{p.product_name} ({p.product_code})  |  "
        f"Safety Data Sheet  |  "
        f"According to OSHA HCS 2012, 29 CFR 1910.1200  |  "
        f"Prepared {p.preparation_date}"
    )
    canvas.drawString(MARGIN, 12 * mm, left_text)

    mfr = p.manufacturer
    if mfr.emergency_provider and mfr.emergency_phone:
        emerg = f"EMERGENCY: {mfr.emergency_provider} {mfr.emergency_phone}"
        canvas.drawString(MARGIN, 8 * mm, emerg)

    canvas.drawRightString(PAGE_W - MARGIN, 8 * mm, f"Page {doc.page}")


# ---------------------------------------------------------------------------
# Cover header
# ---------------------------------------------------------------------------

def _build_sds_cover_header(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    c_primary = _hex(brand.primary)
    c_white   = colors.white

    # Logo gets a fixed, bounded box on the left so it can never bleed
    # under the title; title block is right-aligned, away from the logo.
    logo_w = 42 * mm
    code_w = 35 * mm
    mid_w  = CONTENT_W - logo_w - code_w
    logo_cell = _logo_cell(brand, 16 * mm, logo_w - 4 * mm)

    name_para = Paragraph(
        _esc(p.product_name or "Product Name"),
        ParagraphStyle("CvrName", fontName=FONT_BOLD, fontSize=16,
                       textColor=c_white, leading=20, alignment=TA_RIGHT),
    )
    sub_para = Paragraph(
        _esc(f"Safety Data Sheet  |  {p.product_type}".strip(" |")),
        ParagraphStyle("CvrSub", fontName=FONT_BODY, fontSize=8,
                       textColor=colors.HexColor("#C8D8F8"), leading=11,
                       alignment=TA_RIGHT),
    )
    std_para = Paragraph(
        "According to OSHA Hazard Communication Standard, 29 CFR 1910.1200",
        ParagraphStyle("CvrStd", fontName=FONT_IT, fontSize=7,
                       textColor=colors.HexColor("#A0C0E8"), leading=10,
                       alignment=TA_RIGHT),
    )
    code_para = Paragraph(
        _esc(p.product_code),
        ParagraphStyle("CvrCode", fontName=FONT_BODY, fontSize=8,
                       textColor=colors.HexColor("#C8D8F8"), alignment=TA_RIGHT),
    )
    date_para = Paragraph(
        f"Preparation Date: {p.preparation_date}",
        ParagraphStyle("CvrDate", fontName=FONT_BODY, fontSize=7,
                       textColor=colors.HexColor("#A0C0E8"), alignment=TA_RIGHT),
    )

    header_tbl = Table(
        [[logo_cell, [name_para, sub_para, std_para], [code_para, date_para]]],
        colWidths=[logo_w, mid_w, code_w],
        rowHeights=[24 * mm],
    )
    header_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), c_primary),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("BOX",          (0, 0), (-1, -1), 0, c_primary),
    ]))
    return [header_tbl, Spacer(1, 4 * mm)]


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def build_section_1_identification(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    elems: list = []
    mfr = p.manufacturer
    addr = f"{mfr.company_name}\n{mfr.address_line1}\n{mfr.city_state_zip}"
    if mfr.country:
        addr += f"\n{mfr.country}"

    rows = [["Field", "Information"]]
    _add_row = lambda label, val: rows.append([label, val]) if val else None
    _add_row("Product Name",         p.product_name)
    _add_row("Product Code",         p.product_code)
    _add_row("Recommended Use",      p.recommended_use)
    _add_row("Uses Advised Against", p.restrictions_on_use)
    rows.append(["Manufacturer",
                 Paragraph(_esc(addr).replace("\n", "<br/>"),
                            ParagraphStyle("AddrCell", fontName=FONT_BODY,
                                           fontSize=8, leading=11))])
    _add_row("Phone",    mfr.phone)
    _add_row("Website",  mfr.website)
    if mfr.emergency_provider and mfr.emergency_phone:
        rows.append(["Emergency Phone",
                     f"{mfr.emergency_provider}: {mfr.emergency_phone}"
                     + (f" (Account No.: {mfr.emergency_account})" if mfr.emergency_account else "")])

    tbl = _two_col_table(rows, brand, col_widths=[CONTENT_W * 0.28, CONTENT_W * 0.72])
    elems.append(CondPageBreak(26 * mm))
    elems.append(KeepTogether([_section_bar("SECTION 1: IDENTIFICATION", styles, brand),
                                Spacer(1, 2*mm), tbl]))
    elems.append(Spacer(1, 3 * mm))
    return elems


def build_section_2_hazards(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    elems: list = []
    clf = p.classification
    bar = _section_bar("SECTION 2: HAZARD(S) IDENTIFICATION", styles, brand)

    # --- GHS Classification table ---
    clf_rows = [["Hazard Class", "Category"]]
    for cat in clf.categories:
        clf_rows.append([_esc(cat.class_name), f"Category {cat.category}"])
    clf_tbl = _two_col_table(clf_rows, brand,
                              col_widths=[CONTENT_W * 0.72, CONTENT_W * 0.28])

    # --- Signal word banner ---
    sw_upper = (clf.signal_word or "DANGER").upper()
    sw_color = (colors.HexColor("#CC0000") if "DANGER" in sw_upper
                else colors.HexColor("#E87400"))
    sw_tbl = Table(
        [[Paragraph(f"<b>{_esc(sw_upper)}</b>",
                    ParagraphStyle("SW", fontName=FONT_BOLD, fontSize=18,
                                   textColor=colors.white, alignment=TA_CENTER))]],
        colWidths=[60 * mm], rowHeights=[12 * mm],
    )
    sw_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), sw_color),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",   (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
    ]))
    sw_tbl.hAlign = "CENTER"

    # --- Pictogram row ---
    pic_row = _draw_pictogram_row(clf.pictograms_needed, brand)

    elems.append(KeepTogether([bar, Spacer(1, 2*mm),
                                Paragraph("GHS Classification:", styles["subhead"]),
                                clf_tbl, Spacer(1, 3*mm)]))

    label_block = [
        Paragraph("Label Elements", styles["subhead"]),
        Spacer(1, 1 * mm),
        Paragraph("<b>Hazard Pictograms:</b>", styles["body"]),
        Spacer(1, 2 * mm),
        *pic_row,
        Spacer(1, 5 * mm),
        sw_tbl,
        Spacer(1, 3 * mm),
    ]
    elems.append(KeepTogether(label_block))

    # --- H-statements ---
    elems.append(Paragraph("<b>Hazard statements:</b>", styles["body"]))
    for stmt in clf.all_h_statements:
        elems.append(Paragraph(f"• {_esc(stmt)}", styles["bullet"]))
    elems.append(Spacer(1, 2 * mm))

    # --- P-statements (grouped by prefix) ---
    elems.append(Paragraph("<b>Precautionary Statements:</b>", styles["body"]))
    for stmt in clf.all_p_statements:
        elems.append(Paragraph(_esc(stmt), styles["bullet_small"]))
    elems.append(Spacer(1, 2 * mm))

    # Hazards not otherwise classified
    elems.append(Paragraph("<b>Hazards Not Otherwise Classified:</b> None",
                            styles["body"]))
    elems.append(Spacer(1, 3 * mm))
    return elems


def build_section_3_composition(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    elems: list = []
    c_sec = _hex(brand.secondary)
    c_lt  = _hex(brand.light_bg)

    # Column widths must sum to CONTENT_W (180mm)
    col_w = [73*mm, 33*mm, 22*mm, 22*mm, 30*mm]

    style_h = ParagraphStyle("th3", fontName=FONT_BOLD, fontSize=8,
                              textColor=colors.white, leading=10)
    style_b = ParagraphStyle("td3", fontName=FONT_BODY, fontSize=8,
                              textColor=colors.HexColor("#1C1C1C"), leading=10)

    def _num(v: float) -> str:
        return f"{v:g}"

    # Standard GHS disclosure bands for the fuzzy/proprietary view.
    _BAND_EDGES = [0.0, 0.1, 1.0, 5.0, 10.0, 30.0, 60.0, 100.0]

    def _band(lo: float, hi: float) -> tuple[str, str]:
        if hi <= 0.1:
            return "—", "< 0.1"
        # lower edge = lower bound of the band containing lo;
        # upper edge = upper bound of the band containing hi (widens the range).
        lo_edge = max((e for e in _BAND_EDGES if e <= max(lo, 0.1)), default=0.1)
        hi_edge = min((e for e in _BAND_EDGES if e >= hi), default=100.0)
        if lo_edge < 0.1:
            lo_edge = 0.1
        return _num(lo_edge), _num(hi_edge)

    def _pct(ing) -> tuple[str, str]:
        lo, hi = ing.wt_percent_low, ing.wt_percent_high
        if p.fuzzy_formula:
            return _band(lo, hi)
        if lo == 0 and hi == 0:
            return "—", "< 0.1"          # trace component (still disclosed)
        return _num(lo), _num(hi)

    clf = p.classification
    known = set(getattr(clf, "classified_ingredients", []) or [])
    hazardous = set(getattr(clf, "hazardous_ingredients", []) or [])

    def _aggregatable(ing) -> bool:
        # Only known-and-non-hazardous components may be aggregated. Unknown
        # CAS or anything that triggered a hazard is always disclosed.
        return (p.fuzzy_formula and ing.name in known
                and ing.name not in hazardous)

    header = [Paragraph(h, style_h) for h in
               ["Chemical Name", "CAS Number", "Wt% Low", "Wt% High", "Function"]]
    rows = [header]
    agg_lo = agg_hi = 0.0
    agg_n = 0
    for ing in p.ingredients:
        if _aggregatable(ing):
            agg_lo += ing.wt_percent_low
            agg_hi += ing.wt_percent_high
            agg_n += 1
            continue
        lo, hi = _pct(ing)
        rows.append([
            Paragraph(_esc(ing.name), style_b),
            Paragraph(_esc(ing.cas_number), style_b),
            Paragraph(lo, style_b),
            Paragraph(hi, style_b),
            Paragraph(_esc(ing.function) or "Not specified", style_b),
        ])
    if agg_n:
        blo, bhi = _band(agg_lo, agg_hi)
        rows.append([
            Paragraph("Other ingredients (non-hazardous to health and the "
                      "environment)", style_b),
            Paragraph("Proprietary", style_b),
            Paragraph(blo, style_b),
            Paragraph(bhi, style_b),
            Paragraph("Proprietary", style_b),
        ])

    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  c_sec),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, c_lt]),
        ("GRID",           (0, 0), (-1, -1), 0.5, colors.HexColor("#C8D8E8")),
        ("BOX",            (0, 0), (-1, -1), 1.0, _hex(brand.secondary)),
        ("LEFTPADDING",    (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 4),
        ("TOPPADDING",     (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 3),
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
    ]))

    block = [
        _section_bar("SECTION 3: COMPOSITION/INFORMATION ON INGREDIENTS", styles, brand),
        Spacer(1, 2*mm), tbl, Spacer(1, 1*mm),
    ]
    if p.fuzzy_formula:
        block.append(Paragraph(
            "<i>The specific chemical identity and/or exact percentage of some "
            "components is withheld as a trade secret. Concentrations are "
            "disclosed as ranges; all hazardous components and the hazards of "
            "this product are fully reflected in this Safety Data Sheet.</i>",
            styles["body_small"]))
        block.append(Spacer(1, 1*mm))
    block.append(Paragraph(
        "<i>Additional Information: " + _esc(p.additional_ingredient_info) + "</i>",
        styles["body_small"]))
    elems.append(CondPageBreak(34 * mm))
    elems.extend(block)
    elems.append(Spacer(1, 3 * mm))
    return elems


def build_section_4_first_aid(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    elems: list = []
    rows = [["Route", "First Aid Measures"]]
    _r = lambda lbl, val: rows.append([lbl, val]) if val else None
    if p.first_aid_general:
        rows.append(["General Notes", p.first_aid_general])
    _r("After Inhalation", p.first_aid_inhalation)
    _r("After Skin Contact", p.first_aid_skin)
    _r("After Eye Contact", p.first_aid_eye)
    _r("After Swallowing", p.first_aid_ingestion)

    tbl = _two_col_table(rows, brand, col_widths=[CONTENT_W * 0.25, CONTENT_W * 0.75])

    symptoms_rows = [["Item", "Information"]]
    if p.first_aid_symptoms:
        symptoms_rows.append(["Most Important Symptoms", p.first_aid_symptoms])
    symptoms_rows.append(["Notes for Doctor", p.first_aid_doctor_notes])
    symptoms_tbl = _two_col_table(symptoms_rows, brand,
                                   col_widths=[CONTENT_W * 0.3, CONTENT_W * 0.7])

    elems.append(CondPageBreak(34 * mm))
    elems.append(_section_bar("SECTION 4: FIRST AID MEASURES", styles, brand))
    elems.append(Spacer(1, 2*mm))
    elems.append(Paragraph("Description of First Aid Measures", styles["subhead"]))
    elems.append(tbl)
    elems.append(Spacer(1, 2 * mm))
    elems.append(CondPageBreak(22 * mm))
    elems.append(Paragraph("Most Important Symptoms and Immediate Medical Attention", styles["subhead"]))
    elems.append(symptoms_tbl)
    elems.append(Spacer(1, 3 * mm))
    return elems


def build_section_5_firefighting(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    elems: list = []
    rows = [["Item", "Details"]]
    _r = lambda lbl, val: rows.append([lbl, val]) if val else None
    _r("Suitable Extinguishing Media",   p.extinguishing_media)
    _r("Unsuitable Extinguishing Media", p.unsuitable_extinguishing_media)
    _r("Specific Hazards During Fire-Fighting", p.firefighting_hazards)
    _r("Special Protective Equipment for Firefighters", p.firefighting_ppe)
    _r("Special Precautions",            p.firefighting_precautions)
    tbl = _two_col_table(rows, brand, col_widths=[CONTENT_W * 0.32, CONTENT_W * 0.68])
    elems.append(CondPageBreak(30 * mm))
    elems.append(_section_bar("SECTION 5: FIREFIGHTING MEASURES", styles, brand))
    elems.append(Spacer(1, 2*mm))
    elems.append(tbl)
    elems.append(Spacer(1, 3 * mm))
    return elems


def build_section_6_release(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    elems: list = []
    rows = [["Item", "Measures"]]
    _r = lambda lbl, val: rows.append([lbl, val]) if val else None
    _r("Personal Precautions, Protective Equipment, and Emergency Procedures",
       p.spill_personal_precautions)
    _r("Environmental Precautions", p.spill_environmental_precautions)
    _r("Methods and Material for Containment and Cleaning Up", p.spill_containment_cleanup)
    _r("Reference to Other Sections",
       "For personal protective equipment see Section 8. For disposal see Section 13.")
    tbl = _two_col_table(rows, brand, col_widths=[CONTENT_W * 0.32, CONTENT_W * 0.68])
    elems.append(CondPageBreak(30 * mm))
    elems.append(_section_bar("SECTION 6: ACCIDENTAL RELEASE MEASURES", styles, brand))
    elems.append(Spacer(1, 2*mm))
    elems.append(tbl)
    elems.append(Spacer(1, 3 * mm))
    return elems


def build_section_7_handling(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    elems: list = []
    rows_h = [["Item", "Details"]]
    if p.handling_precautions:
        rows_h.append(["Precautions for Safe Handling", p.handling_precautions])
    rows_s = [["Item", "Details"]]
    if p.storage_conditions:
        rows_s.append(["Conditions for Safe Storage, Including Any Incompatibilities",
                        p.storage_conditions])
    if p.specific_end_use:
        rows_s.append(["Specific End Use(s)", p.specific_end_use])

    elems.append(CondPageBreak(28 * mm))
    elems.append(_section_bar("SECTION 7: HANDLING AND STORAGE", styles, brand))
    elems.append(Spacer(1, 2 * mm))
    if len(rows_h) > 1:
        elems.append(_two_col_table(rows_h, brand,
                                     col_widths=[CONTENT_W * 0.32, CONTENT_W * 0.68]))
        elems.append(Spacer(1, 2 * mm))
    if len(rows_s) > 1:
        elems.append(_two_col_table(rows_s, brand,
                                     col_widths=[CONTENT_W * 0.32, CONTENT_W * 0.68]))
    elems.append(Spacer(1, 3 * mm))
    return elems


def build_section_8_exposure(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    elems: list = []
    c_sec = _hex(brand.secondary)
    c_lt  = _hex(brand.light_bg)

    bar = _section_bar("SECTION 8: EXPOSURE CONTROLS/PERSONAL PROTECTION", styles, brand)
    elems.append(bar)
    elems.append(Spacer(1, 2 * mm))

    # OEL table — 4 columns: 35/75/25/45mm = 180mm
    if p.control_parameters:
        elems.append(Paragraph("Occupational Exposure Limit Values:", styles["subhead"]))
        oel_col_w = [35*mm, 75*mm, 25*mm, 45*mm]
        style_h = ParagraphStyle("oelh", fontName=FONT_BOLD, fontSize=7.5,
                                  textColor=colors.white, leading=10)
        style_b = ParagraphStyle("oelb", fontName=FONT_BODY, fontSize=7.5,
                                  textColor=colors.HexColor("#1C1C1C"), leading=10)
        hdr = [Paragraph(h, style_h) for h in
                ["Authority", "Substance", "Type", "Permissible Concentration"]]
        oel_rows = [hdr]
        prev_substance = ""
        for oel in p.control_parameters:
            row_bg = c_lt if oel.substance_name != prev_substance else None
            oel_rows.append([
                Paragraph(_esc(oel.authority), style_b),
                Paragraph(_esc(oel.substance_name), style_b),
                Paragraph(_esc(oel.oel_type), style_b),
                Paragraph(_esc(f"{oel.value} {oel.unit}"), style_b),
            ])
            prev_substance = oel.substance_name

        oel_tbl = Table(oel_rows, colWidths=oel_col_w, repeatRows=1)
        oel_tbl.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0),  c_sec),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, c_lt]),
            ("GRID",         (0, 0), (-1, -1), 0.4, colors.HexColor("#C8D8E8")),
            ("BOX",          (0, 0), (-1, -1), 1.0, _hex(brand.secondary)),
            ("LEFTPADDING",  (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING",   (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ]))
        elems.append(oel_tbl)
        elems.append(Paragraph(
            "<i>TWA = Time-Weighted Average; STEL = Short-Term Exposure Limit; "
            "IDLH = Immediately Dangerous to Life or Health; "
            "PEL = Permissible Exposure Limit</i>",
            styles["body_small"],
        ))
        elems.append(Spacer(1, 2 * mm))

    # Biological limits
    elems.append(Paragraph(
        f"<b>Biological Limit Values:</b> {_esc(p.biological_limit_values)}",
        styles["body"],
    ))
    elems.append(Spacer(1, 2 * mm))

    # Engineering + PPE table
    ppe_rows = [["Item", "Details"]]
    _r = lambda lbl, val: ppe_rows.append([lbl, val]) if val else None
    _r("Appropriate Engineering Controls", p.engineering_controls)
    _r("Respiratory Protection",  p.ppe_respiratory)
    _r("Hand Protection",         p.ppe_hand)
    _r("Eye and Face Protection", p.ppe_eye)
    _r("Skin and Body Protection",p.ppe_skin)
    _r("General Hygienic Measures", p.hygienic_measures)
    if len(ppe_rows) > 1:
        elems.append(Paragraph("Personal Protection Equipment", styles["subhead"]))
        elems.append(_two_col_table(ppe_rows, brand,
                                     col_widths=[CONTENT_W * 0.3, CONTENT_W * 0.7]))

    elems.append(Spacer(1, 3 * mm))
    return elems


def build_section_9_properties(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    elems: list = []
    pp = p.physical_properties
    _na = "Not determined or not available."

    rows = [["Property", "Value"]]
    fields = [
        ("Appearance",                    pp.appearance),
        ("Odor",                          pp.odour),
        ("Odor Threshold",                pp.odour_threshold or _na),
        ("pH",                            pp.pH),
        ("Melting Point/Freezing Point",  pp.melting_point or _na),
        ("Initial Boiling Point/Range",   pp.boiling_point or _na),
        ("Flash Point (closed cup)",      pp.flash_point or _na),
        ("Evaporation Rate",              pp.evaporation_rate or _na),
        ("Flammability (solid, gas)",     pp.flammability or _na),
        ("Upper Flammability/Explosive Limit", pp.upper_explosive_limit or _na),
        ("Lower Flammability/Explosive Limit", pp.lower_explosive_limit or _na),
        ("Vapor Pressure",                pp.vapour_pressure or _na),
        ("Vapor Density",                 pp.vapour_density or _na),
        ("Density",                       pp.density or _na),
        ("Relative Density",              pp.relative_density or _na),
        ("Solubility(ies)",               pp.solubility or _na),
        ("Partition Coefficient (n-octanol/water)", pp.partition_coefficient or _na),
        ("Auto/Self-ignition Temperature", pp.auto_ignition_temp or _na),
        ("Decomposition Temperature",     pp.decomposition_temp or _na),
        ("Viscosity",                     pp.viscosity or _na),
    ]
    for label, val in fields:
        if val:
            rows.append([label, _esc(val)])

    tbl = _two_col_table(rows, brand, col_widths=[CONTENT_W * 0.38, CONTENT_W * 0.62])
    elems.append(CondPageBreak(34 * mm))
    elems.append(_section_bar("SECTION 9: PHYSICAL AND CHEMICAL PROPERTIES", styles, brand))
    elems.append(Spacer(1, 2*mm))
    elems.append(Paragraph("Information on Basic Physical and Chemical Properties", styles["subhead"]))
    elems.append(tbl)
    elems.append(Spacer(1, 3 * mm))
    return elems


def build_section_10_stability(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    elems: list = []
    rows = [["Item", "Information"]]
    _r = lambda lbl, val: rows.append([lbl, val]) if val else None
    _r("Reactivity",                  p.reactivity)
    _r("Chemical Stability",          p.chemical_stability)
    _r("Possibility of Hazardous Reactions", p.hazardous_reactions)
    _r("Conditions to Avoid",         p.conditions_to_avoid)
    _r("Incompatible Materials",      p.incompatible_materials)
    _r("Hazardous Decomposition Products", p.hazardous_decomposition)
    tbl = _two_col_table(rows, brand, col_widths=[CONTENT_W * 0.32, CONTENT_W * 0.68])
    elems.append(CondPageBreak(30 * mm))
    elems.append(_section_bar("SECTION 10: STABILITY AND REACTIVITY", styles, brand))
    elems.append(Spacer(1, 2*mm))
    elems.append(tbl)
    elems.append(Spacer(1, 3 * mm))
    return elems


def build_section_11_toxicology(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    elems: list = []
    c_sec = _hex(brand.secondary)
    c_lt  = _hex(brand.light_bg)

    elems.append(CondPageBreak(28 * mm))
    elems.append(_section_bar("SECTION 11: TOXICOLOGICAL INFORMATION", styles, brand))
    elems.append(Spacer(1, 2 * mm))

    # Acute toxicity LD50/LC50 table — 4 columns
    if p.toxicology_records:
        elems.append(Paragraph("Acute Toxicity — Substance Data:", styles["subhead"]))
        col_w = [50*mm, 30*mm, 28*mm, 72*mm]
        style_h = ParagraphStyle("toxh", fontName=FONT_BOLD, fontSize=7.5,
                                  textColor=colors.white, leading=10)
        style_b = ParagraphStyle("toxb", fontName=FONT_BODY, fontSize=7.5,
                                  textColor=colors.HexColor("#1C1C1C"), leading=10)
        hdr = [Paragraph(h, style_h) for h in ["Name", "Route", "Species", "Result"]]
        tox_rows = [hdr]
        for rec in p.toxicology_records:
            tox_rows.append([
                Paragraph(_esc(rec.substance), style_b),
                Paragraph(_esc(rec.route.capitalize()), style_b),
                Paragraph(_esc(rec.species), style_b),
                Paragraph(_esc(rec.result), style_b),
            ])
        tox_tbl = Table(tox_rows, colWidths=col_w, repeatRows=1)
        tox_tbl.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0),  c_sec),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, c_lt]),
            ("GRID",           (0, 0), (-1, -1), 0.4, colors.HexColor("#C8D8E8")),
            ("BOX",            (0, 0), (-1, -1), 1.0, _hex(brand.secondary)),
            ("LEFTPADDING",    (0, 0), (-1, -1), 4),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 4),
            ("TOPPADDING",     (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 2),
            ("VALIGN",         (0, 0), (-1, -1), "TOP"),
        ]))
        elems.append(tox_tbl)
        elems.append(Spacer(1, 2 * mm))

    # Other toxicological endpoints
    endpoint_rows = [["Endpoint", "Assessment"]]
    _r = lambda lbl, val: endpoint_rows.append([lbl, val]) if val else None
    _r("Skin Corrosion/Irritation",   p.skin_corrosion_result)
    _r("Serious Eye Damage/Irritation", p.eye_damage_result)
    _r("Respiratory or Skin Sensitization", p.sensitisation)
    _r("Germ Cell Mutagenicity",      p.mutagenicity)

    # Carcinogenicity combined
    carcino = []
    if p.carcinogenicity_iarc:
        carcino.append(p.carcinogenicity_iarc)
    if p.carcinogenicity_ntp:
        carcino.append(p.carcinogenicity_ntp)
    if p.osha_carcinogens:
        carcino.append(f"OSHA Carcinogens: {p.osha_carcinogens}")
    if carcino:
        endpoint_rows.append(["Carcinogenicity", "\n".join(carcino)])

    _r("Reproductive Toxicity",       p.reproductive_toxicity)
    _r("Specific Target Organ Toxicity (Single Exposure)", p.stot_single)
    _r("Specific Target Organ Toxicity (Repeated Exposure)", p.stot_repeated)
    _r("Aspiration Toxicity",         p.aspiration_hazard)

    if len(endpoint_rows) > 1:
        elems.append(_two_col_table(endpoint_rows, brand,
                                     col_widths=[CONTENT_W * 0.38, CONTENT_W * 0.62]))

    elems.append(Spacer(1, 3 * mm))
    return elems


def build_section_12_ecology(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    elems: list = []
    c_sec = _hex(brand.secondary)
    c_lt  = _hex(brand.light_bg)

    elems.append(CondPageBreak(28 * mm))
    elems.append(_section_bar("SECTION 12: ECOLOGICAL INFORMATION", styles, brand))
    elems.append(Spacer(1, 2 * mm))

    def _aquatic_table(records, title):
        if not records:
            return []
        col_w = [45*mm, 30*mm, 45*mm, 20*mm, 40*mm]
        style_h = ParagraphStyle("aqh", fontName=FONT_BOLD, fontSize=7.5,
                                  textColor=colors.white, leading=10)
        style_b = ParagraphStyle("aqb", fontName=FONT_BODY, fontSize=7.5,
                                  textColor=colors.HexColor("#1C1C1C"), leading=10)
        hdr = [Paragraph(h, style_h) for h in
                ["Substance", "Organism Type", "Organism", "Metric", "Result"]]
        rows = [hdr]
        for r in records:
            rows.append([
                Paragraph(_esc(r.substance), style_b),
                Paragraph(_esc(r.organism_type), style_b),
                Paragraph(_esc(r.organism), style_b),
                Paragraph(_esc(r.metric), style_b),
                Paragraph(_esc(r.value), style_b),
            ])
        tbl = Table(rows, colWidths=col_w, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0),  c_sec),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, c_lt]),
            ("GRID",           (0, 0), (-1, -1), 0.4, colors.HexColor("#C8D8E8")),
            ("BOX",            (0, 0), (-1, -1), 1.0, _hex(brand.secondary)),
            ("LEFTPADDING",    (0, 0), (-1, -1), 4),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 4),
            ("TOPPADDING",     (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 2),
            ("VALIGN",         (0, 0), (-1, -1), "TOP"),
        ]))
        return [Paragraph(title, styles["subhead"]), tbl, Spacer(1, 2*mm)]

    elems += _aquatic_table(p.aquatic_tox_records, "Acute (Short-Term) Toxicity — Substance Data:")
    elems += _aquatic_table(p.chronic_tox_records, "Chronic (Long-Term) Toxicity — Substance Data:")

    # Other ecological parameters
    eco_rows = [["Parameter", "Assessment"]]
    _r = lambda lbl, val: eco_rows.append([lbl, val]) if val else None
    for name, text in p.persistence_degradability:
        eco_rows.append([f"Persistence and Degradability — {name}", text])
    for name, text in p.bioaccumulation:
        eco_rows.append([f"Bioaccumulative Potential — {name}", text])
    for name, text in p.mobility:
        eco_rows.append([f"Mobility in Soil — {name}", text])
    _r("Results of PBT and vPvB Assessment", p.pbt_vpvb)
    _r("Other Adverse Effects", p.other_adverse_effects)
    if len(eco_rows) > 1:
        elems.append(_two_col_table(eco_rows, brand,
                                     col_widths=[CONTENT_W * 0.35, CONTENT_W * 0.65]))

    elems.append(Spacer(1, 3 * mm))
    return elems


def build_section_13_disposal(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    elems: list = []
    rows = [["Item", "Details"]]
    if p.disposal_methods:
        rows.append(["Disposal Methods", p.disposal_methods])
    if p.disposal_container:
        rows.append(["Contaminated Packages", p.disposal_container])
    tbl = _two_col_table(rows, brand, col_widths=[CONTENT_W * 0.28, CONTENT_W * 0.72])
    elems.append(CondPageBreak(28 * mm))
    elems.append(_section_bar("SECTION 13: DISPOSAL CONSIDERATIONS", styles, brand))
    elems.append(Spacer(1, 2*mm))
    elems.append(tbl)
    elems.append(Spacer(1, 3 * mm))
    return elems


def build_section_14_transport(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    elems: list = []
    elems.append(CondPageBreak(28 * mm))
    elems.append(_section_bar("SECTION 14: TRANSPORT INFORMATION", styles, brand))
    elems.append(Spacer(1, 2 * mm))

    for ti in p.transport:
        rows = [["Field", "Value"]]
        rows.append(["UN Number",             ti.un_number or "Not regulated"])
        rows.append(["UN Proper Shipping Name",ti.proper_shipping_name or "Not regulated"])
        rows.append(["UN Transport Hazard Class(es)", ti.hazard_class or "None"])
        rows.append(["Packing Group",          ti.packing_group or "None"])
        rows.append(["Labels Required",        ti.labels_required or "None"])
        rows.append(["Environmental Hazards",  ti.environmental_hazard or "None"])
        rows.append(["Special Precautions for User", ti.special_precautions or "None"])
        tbl = _two_col_table(rows, brand, col_widths=[CONTENT_W * 0.35, CONTENT_W * 0.65])
        elems.append(KeepTogether([
            Paragraph(ti.mode, styles["subhead"]),
            tbl,
            Spacer(1, 2*mm),
        ]))

    elems.append(Spacer(1, 1 * mm))
    return elems


def build_section_15_regulatory(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    elems: list = []
    c_sec = _hex(brand.secondary)
    c_lt  = _hex(brand.light_bg)

    elems.append(CondPageBreak(28 * mm))
    elems.append(_section_bar("SECTION 15: REGULATORY INFORMATION", styles, brand))
    elems.append(Spacer(1, 2 * mm))
    elems.append(Paragraph("United States Regulations", styles["subhead"]))

    # TSCA / SNUR / Export notice
    for label, val in [
        ("Inventory Listing (TSCA):", p.tsca_inventory),
        ("Significant New Use Rule (TSCA Section 5):", p.tsca_snur),
        ("Export Notification under TSCA Section 12(b):", p.tsca_export),
    ]:
        elems.append(Paragraph(f"<b>{_esc(label)}</b> {_esc(val)}", styles["body"]))
    elems.append(Spacer(1, 2 * mm))

    # Regulatory table: Substance | SARA302 | SARA313 | CERCLA | RCRA | CAA112r | Prop65
    if p.regulatory_listings:
        # 7 columns: 50/15/15/20/15/15/50mm = 180mm
        col_w = [50*mm, 15*mm, 15*mm, 20*mm, 15*mm, 15*mm, 50*mm]
        style_h = ParagraphStyle("regh", fontName=FONT_BOLD, fontSize=7,
                                  textColor=colors.white, leading=9)
        style_b = ParagraphStyle("regb", fontName=FONT_BODY, fontSize=7,
                                  textColor=colors.HexColor("#1C1C1C"), leading=9)
        hdr = [Paragraph(h, style_h) for h in
                ["Substance (CAS)", "SARA\n302", "SARA\n313",
                 "CERCLA\n(RQ lbs)", "RCRA", "CAA\n112(r)", "Prop 65 Warning"]]
        reg_rows = [hdr]
        for rl in p.regulatory_listings:
            cas_str = f"{rl.substance_name}\n{rl.cas}"
            cercla = rl.cercla_rq_lbs if rl.cercla_listed else "No"
            reg_rows.append([
                Paragraph(_esc(cas_str).replace("\n","<br/>"), style_b),
                Paragraph("Yes" if rl.sara_302 else "No", style_b),
                Paragraph("Yes" if rl.sara_313 else "No", style_b),
                Paragraph(f"Yes/{cercla}" if rl.cercla_listed else "No", style_b),
                Paragraph(_esc(rl.rcra_code) or "—", style_b),
                Paragraph("Yes" if rl.caa_112r else "No", style_b),
                Paragraph(_esc(rl.prop_65_warning or ("Yes" if rl.prop_65 else "No")), style_b),
            ])
        reg_tbl = Table(reg_rows, colWidths=col_w, repeatRows=1)
        reg_tbl.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0),  c_sec),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, c_lt]),
            ("GRID",           (0, 0), (-1, -1), 0.4, colors.HexColor("#C8D8E8")),
            ("BOX",            (0, 0), (-1, -1), 1.0, _hex(brand.secondary)),
            ("LEFTPADDING",    (0, 0), (-1, -1), 3),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 3),
            ("TOPPADDING",     (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 2),
            ("VALIGN",         (0, 0), (-1, -1), "TOP"),
        ]))
        elems.append(reg_tbl)
        elems.append(Spacer(1, 2 * mm))

    # State right-to-know listings
    state_rows: dict[str, list[str]] = {}
    for rl in p.regulatory_listings:
        for st in rl.rtk_states:
            state_rows.setdefault(st, []).append(rl.substance_name)
    if state_rows:
        rtk_table_rows = [["State", "Listed Substances"]]
        for state, names in sorted(state_rows.items()):
            rtk_table_rows.append([
                f"{state} Right to Know",
                "; ".join(names),
            ])
        elems.append(Paragraph("State Right-to-Know Listings:", styles["subhead"]))
        elems.append(_two_col_table(rtk_table_rows, brand,
                                     col_widths=[CONTENT_W * 0.28, CONTENT_W * 0.72]))
        elems.append(Spacer(1, 2 * mm))

    # California Prop 65
    if p.prop_65_warning_text:
        elems.append(Paragraph(
            f"<b>California Proposition 65:</b> {_esc(p.prop_65_warning_text)}",
            styles["body"],
        ))

    elems.append(Spacer(1, 3 * mm))
    return elems


def build_section_16_other(p: SDSProduct, brand: BrandConfig, styles: dict) -> list:
    elems: list = []
    rows = [["Item", "Information"]]
    _r = lambda lbl, val: rows.append([lbl, val]) if val else None
    _r("Initial Preparation Date", p.preparation_date)
    _r("Revision Date",            p.revision_date)
    _r("Revision Number",          p.revision_number)
    _r("Supersedes",               p.supersedes)
    _r("Prepared By",              p.prepared_by)
    _r("Abbreviations",            p.abbreviations)
    tbl = _two_col_table(rows, brand, col_widths=[CONTENT_W * 0.28, CONTENT_W * 0.72])

    elems.append(CondPageBreak(70 * mm))
    elems.append(KeepTogether([
        _section_bar("SECTION 16: OTHER INFORMATION", styles, brand),
        Spacer(1, 2*mm), tbl,
        Spacer(1, 4*mm),
        *_nfpa_hmis_block(p, styles),
    ]))
    elems.append(Spacer(1, 3 * mm))

    elems.append(HRFlowable(width=CONTENT_W, thickness=0.5,
                              color=colors.HexColor("#AAAAAA")))
    elems.append(Spacer(1, 2 * mm))
    elems.append(Paragraph("<b>Disclaimer:</b>", styles["subhead"]))
    elems.append(Paragraph(_esc(p.disclaimer), styles["body_small"]))
    elems.append(Spacer(1, 2 * mm))
    elems.append(Paragraph("End of Safety Data Sheet", styles["body_small"]))
    return elems


# ---------------------------------------------------------------------------
# Pictogram rendering
# ---------------------------------------------------------------------------

# Text labels used in programmatic fallback
_PICTOGRAM_LABELS = {
    "GHS01": "Expl",   # explosive
    "GHS02": "Flame",  # flammable
    "GHS03": "OX",     # oxidizer
    "GHS04": "Gas",    # compressed gas
    "GHS05": "COR",    # corrosion
    "GHS06": "Skull",  # acute toxicity
    "GHS07": "!",      # health hazard (exclamation)
    "GHS08": "Bio",    # serious health hazard
    "GHS09": "Env",    # environmental
}

# Diamond colors per pictogram class
_PICTOGRAM_COLORS = {
    "GHS01": "#CC0000",
    "GHS02": "#CC0000",
    "GHS03": "#CC8800",
    "GHS04": "#4488CC",
    "GHS05": "#CC0000",
    "GHS06": "#000000",
    "GHS07": "#CC8800",
    "GHS08": "#CC0000",
    "GHS09": "#008800",
}


def _nfpa_hmis_block(p: SDSProduct, styles: dict) -> list:
    """NFPA 704 colour diamond + HMIS III colour bar (derived ratings)."""
    from reportlab.graphics.shapes import Drawing, Polygon, String

    nf = p.nfpa or {}
    hm = p.hmis or {}
    nh, nf_, ni = (str(nf.get("health", 0)), str(nf.get("flammability", 0)),
                   str(nf.get("instability", 0)))
    nsp = nf.get("special", "") or ""

    # --- NFPA diamond (45 mm) — square rotated 45°, split into 4 triangles ---
    S = 45 * mm
    d = Drawing(S, S)
    c = S / 2
    h = S * 0.34                       # quadrant half-diagonal
    tris = [
        ((c - h, c), (c, c + h), (c, c), "#0000FF", nh),     # left
        ((c, c + h), (c + h, c), (c, c), "#FF0000", nf_),     # top
        ((c + h, c), (c, c - h), (c, c), "#FFFF00", ni),      # right
        ((c, c - h), (c - h, c), (c, c), "#FFFFFF", nsp),     # bottom
    ]
    for (ax, ay), (bx, by), (mx, my), col, val in tris:
        d.add(Polygon([ax, ay, bx, by, mx, my],
                      fillColor=colors.HexColor(col),
                      strokeColor=colors.black, strokeWidth=1))
        tx, ty = (ax + bx + mx) / 3, (ay + by + my) / 3
        fs = 14 if len(str(val)) <= 1 else 9
        d.add(String(tx, ty - fs * 0.36, str(val), fontName=FONT_BOLD,
                      fontSize=fs, textAnchor="middle",
                      fillColor=colors.white if col in ("#0000FF", "#FF0000")
                      else colors.black))
    for lx, ly, txt in ((c, S - 2, "Flammability"), (3, c, "Health"),
                         (S - 3, c, "Instability"), (c, 4, "Special")):
        d.add(String(lx, ly, txt, fontName=FONT_BODY, fontSize=6,
                      textAnchor="middle", fillColor=colors.HexColor("#444444")))

    # --- HMIS III bar ---
    hh = str(hm.get("health", 0)) + ("*" if hm.get("chronic") else "")
    rows = [("HEALTH", "#0000FF", hh),
            ("FLAMMABILITY", "#FF0000", str(hm.get("flammability", 0))),
            ("PHYSICAL HAZARD", "#FFD700", str(hm.get("physical", 0)))]
    th = ParagraphStyle("hmL", fontName=FONT_BOLD, fontSize=9,
                         textColor=colors.white, leading=11)
    tv = ParagraphStyle("hmV", fontName=FONT_BOLD, fontSize=11,
                         textColor=colors.black, alignment=TA_CENTER, leading=13)
    hmis_tbl = Table([[Paragraph(lbl, th if col != "#FFD700"
                                 else ParagraphStyle("hmLk", parent=th,
                                                     textColor=colors.black)),
                       Paragraph(val, tv)] for lbl, col, val in rows],
                     colWidths=[42 * mm, 14 * mm], rowHeights=[8 * mm] * 3)
    hmis_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#0000FF")),
        ("BACKGROUND", (0, 1), (0, 1), colors.HexColor("#FF0000")),
        ("BACKGROUND", (0, 2), (0, 2), colors.HexColor("#FFD700")),
        ("BOX", (0, 0), (-1, -1), 1, colors.black),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    legend = Paragraph(
        "0 = Not significant · 1 = Slight · 2 = Moderate · 3 = High · "
        "4 = Extreme · * = Chronic", styles["body_small"])
    note = Paragraph(
        "<i>NFPA 704 / HMIS III ratings are derived from the GHS "
        "classification (industry heuristic) — review before use.</i>",
        styles["body_small"])

    grid = Table([[
        [Paragraph("<b>NFPA 704</b>", styles["body"]), d],
        [Paragraph("<b>HMIS III</b>", styles["body"]), Spacer(1, 1 * mm),
         hmis_tbl, Spacer(1, 1.5 * mm), legend],
    ]], colWidths=[CONTENT_W * 0.42, CONTENT_W * 0.58])
    grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return [grid, Spacer(1, 2 * mm), note]


def _draw_pictogram_row(codes: list[str], brand: BrandConfig) -> list:
    """Return a list of flowables rendering GHS pictogram diamonds in a row."""
    from reportlab.graphics.shapes import Drawing, Polygon, String, Line
    from reportlab.graphics import renderPDF

    size_mm = 22
    size_pt = size_mm * mm
    pad = 3 * mm
    cell_w = size_pt + pad * 2

    cells = []
    for code in codes:
        # Try PNG asset first
        png_path = _MODULE_DIR / "assets" / "pictograms" / f"{code}.png"
        if png_path.exists():
            try:
                cells.append(Image(str(png_path), width=size_pt, height=size_pt))
                continue
            except Exception:
                pass

        # Programmatic fallback: draw a red-bordered diamond with label
        d = Drawing(size_pt, size_pt)
        cx = size_pt / 2
        cy = size_pt / 2
        half = size_pt * 0.46   # half-diagonal of diamond

        stroke_color = _PICTOGRAM_COLORS.get(code, "#CC0000")

        # White filled diamond
        diamond = Polygon(
            points=[cx, cy + half,          # top
                    cx + half, cy,           # right
                    cx, cy - half,           # bottom
                    cx - half, cy],          # left
            fillColor=colors.white,
            strokeColor=colors.HexColor(stroke_color),
            strokeWidth=2.5,
        )
        d.add(diamond)

        # Label text centered
        label = _PICTOGRAM_LABELS.get(code, code)
        s = String(
            cx, cy - 4,
            label,
            fontName=FONT_BOLD,
            fontSize=9,
            fillColor=colors.HexColor(stroke_color),
            textAnchor="middle",
        )
        d.add(s)
        cells.append(d)

    if not cells:
        return []

    # Place all pictograms in a single-row table
    pic_tbl = Table(
        [cells],
        colWidths=[cell_w] * len(cells),
        rowHeights=[size_pt + pad],
    )
    pic_tbl.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING",  (0, 0), (-1, -1), pad),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",   (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
    ]))
    return [pic_tbl]


# ---------------------------------------------------------------------------
# Shared helper primitives (mirrored from tds_pdf_builder.py)
# ---------------------------------------------------------------------------

def _make_styles(brand: BrandConfig) -> dict:
    c_primary = _hex(brand.primary)
    c_dark = colors.HexColor("#1C1C1C")
    return {
        "body": ParagraphStyle(
            "body", fontName=FONT_BODY, fontSize=8.5, leading=12,
            textColor=c_dark, spaceAfter=2,
        ),
        "body_small": ParagraphStyle(
            "body_small", fontName=FONT_BODY, fontSize=7, leading=10,
            textColor=colors.HexColor("#555555"),
        ),
        "bullet": ParagraphStyle(
            "bullet", fontName=FONT_BODY, fontSize=8.5, leading=12,
            textColor=c_dark, leftIndent=8, spaceAfter=1,
        ),
        "bullet_small": ParagraphStyle(
            "bullet_small", fontName=FONT_BODY, fontSize=7.5, leading=11,
            textColor=colors.HexColor("#333333"), leftIndent=8, spaceAfter=1,
        ),
        "subhead": ParagraphStyle(
            "subhead", fontName=FONT_BOLD, fontSize=8.5, leading=12,
            textColor=c_dark, spaceBefore=4, spaceAfter=2,
        ),
        "section_bar_text": ParagraphStyle(
            "section_bar_text", fontName=FONT_BOLD, fontSize=9.5, leading=13,
            textColor=colors.white,
        ),
    }


def _section_bar(title: str, styles: dict, brand: BrandConfig | None = None):
    bg = _hex(brand.primary) if brand else colors.HexColor("#1A3A5C")
    tbl = Table(
        [[Paragraph(title, styles["section_bar_text"])]],
        colWidths=[CONTENT_W],
        rowHeights=[7.5 * mm],
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), bg),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
    ]))
    return tbl


def _two_col_table(rows: list, brand: BrandConfig,
                   col_widths: list | None = None) -> Table:
    c_sec = _hex(brand.secondary)
    c_lt  = _hex(brand.light_bg)
    if col_widths is None:
        col_widths = [CONTENT_W * 0.3, CONTENT_W * 0.7]

    style_h = ParagraphStyle("th", fontName=FONT_BOLD, fontSize=8,
                              textColor=colors.white, leading=10)
    style_b = ParagraphStyle("td", fontName=FONT_BODY, fontSize=8,
                              textColor=colors.HexColor("#1C1C1C"), leading=10)
    formatted: list = []
    for i, row in enumerate(rows):
        st = style_h if i == 0 else style_b
        formatted.append([
            Paragraph(str(cell), st) if isinstance(cell, str) else cell
            for cell in row
        ])

    tbl = Table(formatted, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),  c_sec),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, c_lt]),
        ("GRID",         (0, 0), (-1, -1), 0.4, colors.HexColor("#C8D8E8")),
        ("BOX",          (0, 0), (-1, -1), 1.0, _hex(brand.secondary)),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
    ]))
    return tbl


def _logo_cell(brand: BrandConfig, height: float, max_w: float | None = None):
    if brand.logo_path:
        logo_p = _resolve_logo(brand.logo_path)
        if logo_p.exists():
            try:
                from PIL import Image as PILImage
                with PILImage.open(logo_p) as img:
                    iw, ih = img.size
                aspect = iw / ih
                logo_h = height
                logo_w = logo_h * aspect
                # Never let a wide wordmark overflow its column and bleed
                # under the title — clamp to max_w, shrink height to match.
                if max_w and logo_w > max_w:
                    logo_w = max_w
                    logo_h = logo_w / aspect
                return Image(str(logo_p), width=logo_w, height=logo_h)
            except Exception:
                pass
    return Paragraph(
        f"<b>{_esc(brand.company_name)}</b>",
        ParagraphStyle("LogoText", fontName=FONT_BOLD, fontSize=9,
                       textColor=colors.white, leading=11),
    )


def _logo_width(brand: BrandConfig, height: float, fallback: float) -> float:
    if brand.logo_path:
        logo_p = _resolve_logo(brand.logo_path)
        if logo_p.exists():
            try:
                from PIL import Image as PILImage
                with PILImage.open(logo_p) as img:
                    iw, ih = img.size
                return height * (iw / ih)
            except Exception:
                pass
    return fallback


def _hex(hex_str: str) -> colors.HexColor:
    return colors.HexColor(hex_str)


def _esc(text: str) -> str:
    """Escape XML special chars for ReportLab Paragraph."""
    if not text:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))
