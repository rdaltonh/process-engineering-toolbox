"""Multi-schedule span tables and PDF export for the Span Chart app."""

from __future__ import annotations

import copy
import io
from dataclasses import dataclass, field
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from proctoolbox_core.io import ProjectWarning
from proctoolbox_core.loads import asce7_16 as asce
from proctoolbox_core.materials import MaterialDatabase, default_database
from proctoolbox_core.piping import list_nps, schedules_for, sort_schedules
from proctoolbox_core.units import display_unit, from_si

from span_calc import (
    CASE_LABELS,
    DEFLECTION,
    END_CONDITIONS,
    OCC_ICE,
    OCC_SEISMIC,
    OCC_SEISMIC_SNOW,
    OCC_SNOW,
    OCC_WIND,
    OCC_WIND_SNOW,
    SUS,
    SpanCalculator,
    SpanInputs,
)

CASE_CODES = {SUS: "S", DEFLECTION: "D", OCC_WIND: "W", OCC_WIND_SNOW: "WS", OCC_SEISMIC: "E",
              OCC_SEISMIC_SNOW: "ES", OCC_ICE: "I", OCC_SNOW: "SN"}


@dataclass
class SpanTables:
    schedules: list[str]
    nps: list[str]
    end_conditions: list[str]
    # cells[end_condition][nps][schedule] = (span_m, governing_case) or None if schedule not listed
    cells: dict[str, dict[str, dict[str, tuple[float, str] | None]]]
    allowable: float
    allowable_citation: str
    E: float
    warnings: list[ProjectWarning] = field(default_factory=list)


def generate_tables(base: SpanInputs, schedules: list[str], nps_list: list[str],
                    db: MaterialDatabase | None = None) -> SpanTables:
    """Run the calculator for each schedule over the NPS range and pivot the governing spans."""
    if not schedules:
        raise ValueError("Select at least one schedule.")
    schedules = sort_schedules(list(schedules))
    db = db or default_database()
    cells = {c: {n: {s: None for s in schedules} for n in nps_list} for c in base.end_conditions}
    warnings: list[ProjectWarning] = []
    seen = set()
    allowable = E = 0.0
    cite = ""
    for sch in schedules:
        inp = copy.deepcopy(base)
        inp.schedule = sch
        inp.nps_list = [n for n in nps_list if sch in schedules_for(n)]
        if not inp.nps_list:
            continue
        res = SpanCalculator(inp, db).run()
        allowable, E, cite = res.allowable, res.E, res.allowable_citation
        for w in res.warnings:
            if (w.code, w.message) not in seen:
                seen.add((w.code, w.message))
                warnings.append(w)
        for sz in res.sizes:
            for ec in sz.by_condition:
                cells[ec.end_condition][sz.nps][sch] = (ec.span, ec.governs)
    used_nps = [n for n in nps_list if any(cells[c][n][s] for c in cells for s in schedules)]
    return SpanTables(schedules, used_nps, list(base.end_conditions), cells, allowable, cite, E, warnings)


def input_summary(inp: SpanInputs, system: str, db: MaterialDatabase | None = None) -> list[tuple[str, str]]:
    """Human-readable (label, value) pairs describing the inputs, in the given unit system."""
    db = db or default_database()

    def fmt(val, kind, nd=2):
        return f"{from_si(val, kind, system):,.{nd}f} {display_unit(kind, system)}"

    rows = [
        ("Material", f"{db.material(inp.material_id).name} ({db.material(inp.material_id).spec})"),
        ("Design temperature", fmt(inp.design_temperature, "temperature", 1)),
        ("Design pressure (gauge)", fmt(inp.design_pressure, "pressure", 1)),
        ("Contents specific gravity", f"{inp.contents_sg:g} (water at 60°F = 1.0)"),
        ("Allowable Sh", "B31.3 Table A-1 at design T" if inp.allowable_override is None
         else f"Override {fmt(inp.allowable_override, 'stress', 0)} ({inp.allowable_override_source or 'no source'})"),
        ("Deflection limit", f"{fmt(inp.deflection_limit, 'deflection', 3)} on pipe + contents "
                             f"({inp.deflection_limit_basis or 'no basis given'})"),
        ("Corrosion allowance / mill tol.", f"{fmt(inp.corrosion_allowance, 'small_length', 3)} / "
                                            f"{'12.5% applied' if inp.mill_tolerance else 'not applied'}"),
        ("End conditions", ", ".join(END_CONDITIONS[c] for c in inp.end_conditions)
         + (f" (continuous: {inp.continuous_spans} spans)" if "continuous" in inp.end_conditions else "")),
    ]
    s = inp.site
    if inp.wind.enabled or inp.snow.enabled or inp.ice.enabled or inp.seismic.enabled:
        rows.append(("Site (ASCE 7-16)", f"Risk Cat. {s.risk_category}, Exposure {s.exposure}, "
                                         f"z = {fmt(s.height, 'length', 1)}, K_zt = {s.kzt:g}, "
                                         f"insulation = {fmt(s.insulation_thickness, 'small_length', 2)}"))
    if inp.wind.enabled:
        rows.append(("Wind", f"V = {fmt(inp.wind.speed, 'speed', 0)}, surface {inp.wind.roughness.replace('_', ' ')}"
                             + (f", C_f override {inp.wind.cf_override:g}" if inp.wind.cf_override else "")))
    if inp.snow.enabled:
        rows.append(("Snow", f"p_g = {fmt(inp.snow.ground_snow, 'area_load', 1)}, {inp.snow.condition.replace('_', ' ')}, "
                             f"treated as {inp.snow.category}"
                             + (", exempt (surface > 45°F)" if inp.snow.surface_above_45F else "")))
    if inp.ice.enabled:
        rows.append(("Ice", f"t = {fmt(inp.ice.thickness, 'small_length', 2)}, V_c = {fmt(inp.ice.concurrent_wind, 'speed', 0)}, "
                            f"treated as {inp.ice.category}"))
    if inp.seismic.enabled:
        pt = asce.piping_types()[inp.seismic.piping_type]
        rows.append(("Seismic", f"S_DS = {inp.seismic.sds:g}, I_p = {inp.seismic.ip:g}, "
                                f"h = {fmt(inp.seismic.structure_height, 'length', 1)}, {pt['label']} "
                                f"(a_p {pt['ap']:g}, R_p {pt['Rp']:g})"))
    if not (inp.wind.enabled or inp.snow.enabled or inp.ice.enabled or inp.seismic.enabled):
        rows.append(("Environmental loads", "None (sustained W + P and deflection only)"))
    return rows


def build_pdf(tables: SpanTables, inp: SpanInputs, system: str, app_version: str,
              generated: datetime | None = None, db: MaterialDatabase | None = None) -> bytes:
    """Render the span tables as a portrait-letter PDF and return its bytes."""
    generated = generated or datetime.now().astimezone()
    stamp = generated.strftime("%Y-%m-%d %H:%M %Z").strip()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.6 * inch,
                            title="Span Chart: Support Spacing Tables", author="Process Engineering Toolbox")
    ss = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=7.5, leading=9.5)
    tiny = ParagraphStyle("tiny", parent=ss["Normal"], fontSize=6.5, leading=8)
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=15, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=11, spaceBefore=8, spaceAfter=4)
    L_u = display_unit("length", system)
    s_u = display_unit("stress", system)

    story = [
        Paragraph("Span Chart: Maximum Support Spacing", h1),
        Paragraph(f"Generated {stamp} · Span Chart v{app_version} · Process Engineering Toolbox", small),
        Spacer(1, 6),
    ]
    rows = input_summary(inp, system, db)
    rows.append(("Allowable used", f"Sh = {from_si(tables.allowable, 'stress', system):,.0f} {s_u} "
                                   f"({tables.allowable_citation}); occasional limit 1.33 Sh"))
    rows.append(("Modulus E", f"{from_si(tables.E, 'modulus', system):.2f} {display_unit('modulus', system)} "
                              "(B31.3 App. C at design T)"))
    hdr = Table([[Paragraph(f"<b>{a}</b>", small), Paragraph(b, small)] for a, b in rows],
                colWidths=[1.8 * inch, 5.7 * inch])
    hdr.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.whitesmoke, colors.white]),
                             ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 2)]))
    story += [hdr, Spacer(1, 4)]

    present = sorted({cell[1] for c in tables.cells.values() for n in c.values() for cell in n.values() if cell},
                     key=list(CASE_CODES).index)
    legend = " · ".join(f"<b>{CASE_CODES[k]}</b> = {CASE_LABELS[k]}" for k in present)
    note = (f"Cells: maximum span in {L_u} and the governing case code. '-' = schedule not listed for that NPS. "
            f"Governing case: {legend}.")

    ncols = len(tables.schedules)
    nps_w = 0.5 * inch
    fs = 7.5 if ncols <= 9 else 6.0  # keep up to all 17 schedules on a 7.5 in portrait width
    col_w = min(0.85 * inch, (7.5 * inch - nps_w) / max(ncols, 1))
    for cond in tables.end_conditions:
        data = [["NPS"] + [f"Sch {s}" for s in tables.schedules]]
        for n in tables.nps:
            row = [n]
            for s in tables.schedules:
                cell = tables.cells[cond][n][s]
                row.append("-" if cell is None else f"{from_si(cell[0], 'length', system):.1f} {CASE_CODES[cell[1]]}")
            data.append(row)
        t = Table(data, colWidths=[nps_w] + [col_w] * ncols, repeatRows=1)
        t.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), "Helvetica", fs),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", fs),
            ("FONT", (0, 1), (0, -1), "Helvetica-Bold", fs),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef2f7")]),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ]))
        story.append(KeepTogether([Paragraph(f"{END_CONDITIONS[cond]}: maximum support span ({L_u})", h2), t]))
        story.append(Paragraph(note, tiny))

    if tables.warnings:
        story.append(Paragraph("Data warnings and assumptions (review before use)", h2))
        for w in tables.warnings:
            story.append(Paragraph(f"• <b>{w.code}</b>: {w.message}", tiny))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Support-spacing estimate for straight horizontal runs per B31.3 302.3.5/302.3.6 with ASCE 7-16 ASD "
        "load combinations. Not a substitute for flexibility/stress analysis of the piping system.", tiny))

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(0.5 * inch, 0.35 * inch, f"Generated {stamp}")
        canvas.drawRightString(letter[0] - 0.5 * inch, 0.35 * inch, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def default_nps_range(lo: str, hi: str) -> list[str]:
    all_nps = list_nps()
    i, j = all_nps.index(lo), all_nps.index(hi)
    return all_nps[min(i, j): max(i, j) + 1]


__all__ = ["CASE_CODES", "SpanTables", "build_pdf", "default_nps_range", "generate_tables", "input_summary"]
