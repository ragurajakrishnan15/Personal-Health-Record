#!/usr/bin/env python
"""Synthetic medical document generator (US + India formats).

Produces prescriptions, lab reports and discharge summaries as clean PDFs or
degraded scans / phone photos, each with a ground-truth JSON answer key.

    python generate.py --count 60 --seed 42 --out output

Output layout:
    output/documents/<id>.pdf | <id>.jpg | <id>_p2.jpg ...
    output/truth/<id>.json        expected extraction + generation metadata
    output/manifest.jsonl         one line per document
    output/patients.json          patient profiles (usable as seed data)

All people, facilities and values are fictional. Documents carry a small
"synthetic sample" footer unless --no-watermark is passed.
"""
import argparse
import datetime as dt
import json
import os
import random
import shutil
import tempfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from faker import Faker
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle, KeepTogether)

import degrade
from data import (ACUTE, COND_WEIGHTS, CONDITIONS, CLINICS, DRUGS, HOSPITALS, IN_COUNCILS,
                  IN_QUALS, LAB_BY_KEY, LABS, LABS_NAMES, PANELS, SCENARIOS, US_QUALS)

esc = lambda s: escape(str(s))
TODAY = dt.date.today()
WATERMARK = "SYNTHETIC SAMPLE - generated for software testing - not a real medical record"

# ══════════════════════════════════════════════════════════════════════
#  Fonts
# ══════════════════════════════════════════════════════════════════════
FONT_FAMILIES = [("Helvetica", "Helvetica-Bold"), ("Times-Roman", "Times-Bold")]
HAND_FONT = None


def register_fonts():
    global HAND_FONT
    wf = r"C:\Windows\Fonts"
    for name, reg, bold in [("Arial", "arial.ttf", "arialbd.ttf"), ("Verdana", "verdana.ttf", "verdanab.ttf"),
                            ("Tahoma", "tahoma.ttf", "tahomabd.ttf"), ("Calibri", "calibri.ttf", "calibrib.ttf")]:
        try:
            pdfmetrics.registerFont(TTFont(name, os.path.join(wf, reg)))
            pdfmetrics.registerFont(TTFont(name + "-Bold", os.path.join(wf, bold)))
            FONT_FAMILIES.append((name, name + "-Bold"))
        except Exception:
            pass
    try:
        pdfmetrics.registerFont(TTFont("Hand", os.path.join(wf, "Inkfree.ttf")))
        HAND_FONT = "Hand"
    except Exception:
        pass


PALETTES = [colors.HexColor(h) for h in
            ["#1f4e79", "#0b6e4f", "#7a1f2b", "#333333", "#2c3e8f", "#8a4b08", "#006d77"]]

# ══════════════════════════════════════════════════════════════════════
#  People
# ══════════════════════════════════════════════════════════════════════


@dataclass
class Patient:
    id: str
    region: str
    name: str
    sex: str
    age: int
    dob: dt.date
    pid: str
    phone: str
    address: str
    conds: list
    allergy: str | None
    strengths: dict = field(default_factory=dict)
    docs: list = field(default_factory=list)


@dataclass
class Doctor:
    name: str          # "Dr. Jane Smith"
    last: str
    quals: str
    reg: str           # NPI / registration number
    extra: str         # DEA / council


ALLERGIES = [("Penicillin", "rash"), ("Sulfa drugs", "hives"), ("Peanuts", "anaphylaxis"), ("Latex", "contact dermatitis")]


def weighted_conditions(region, rng):
    w = COND_WEIGHTS[region]
    n = rng.choices([1, 2, 3], [4, 4, 2])[0]
    chosen = []
    pool = dict(w)
    while len(chosen) < n:
        k = rng.choices(list(pool), list(pool.values()))[0]
        chosen.append(k)
        pool.pop(k)
    return chosen


def make_patient(idx, region, rng, fk):
    sex = rng.choice("MF")
    first = fk.first_name_male() if sex == "M" else fk.first_name_female()
    last = fk.last_name()
    age = rng.randint(28, 78)
    dob = TODAY - dt.timedelta(days=age * 365 + rng.randint(0, 364))
    if region == "US":
        pid = f"MRN{rng.randint(1000000, 9999999)}"
        phone = f"({rng.randint(201, 989)}) {rng.randint(200, 999)}-{rng.randint(1000, 9999)}"
    else:
        pid = f"UHID{rng.randint(100000, 999999)}"
        phone = f"+91 {rng.choice('6789')}{rng.randint(10**8, 10**9 - 1)}"
    allergy = None
    if rng.random() < 0.3:
        a, r = rng.choice(ALLERGIES)
        allergy = f"{a}|{r}"
    return Patient(id=f"{region.lower()}_p{idx:02d}", region=region, name=f"{first} {last}", sex=sex, age=age,
                   dob=dob, pid=pid, phone=phone, address=fk.address().replace("\n", ", "),
                   conds=weighted_conditions(region, rng), allergy=allergy)


def make_doctor(region, rng, fk):
    first, last = fk.first_name(), fk.last_name()
    if region == "US":
        q = rng.choice(US_QUALS)
        return Doctor(f"Dr. {first} {last}", last, q, f"NPI {rng.randint(10**9, 10**10 - 1)}",
                      f"DEA {rng.choice('ABFM')}{rng.choice('ABCDHKLMPRSTW')}{rng.randint(1000000, 9999999)}")
    c = rng.choice(IN_COUNCILS)
    return Doctor(f"Dr. {first} {last}", last, rng.choice(IN_QUALS),
                  f"Reg. No. {c}/{rng.randint(2001, 2020)}/{rng.randint(10000, 99999)}", c)


# ══════════════════════════════════════════════════════════════════════
#  Dates
# ══════════════════════════════════════════════════════════════════════
DATE_FMTS = {"US": ["%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%m-%d-%Y"],
             "IN": ["%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%d-%m-%Y"]}


def pick_datefmt(region, rng):
    return rng.choice(DATE_FMTS[region])


def fd(d, fmt):
    return d.strftime(fmt) if d else ""


# ══════════════════════════════════════════════════════════════════════
#  Medications
# ══════════════════════════════════════════════════════════════════════
FREQ_VERBOSE = {"once daily": "once daily", "twice daily": "twice daily", "three times daily": "three times daily",
                "at bedtime": "at bedtime", "weekly": "once weekly", "as needed": "as needed"}
FREQ_ABBR = {"once daily": "daily", "twice daily": "BID", "three times daily": "TID", "at bedtime": "QHS",
             "weekly": "weekly", "as needed": "PRN"}
TIMING_US = {"morning": "in the morning", "night": "at night", "after food": "after meals",
             "before food": "before meals", "with meals": "with meals", "bedtime": "at bedtime",
             "empty stomach": "on an empty stomach"}
TIMING_ABBR = {"morning": "qAM", "night": "qHS", "after food": "p.c.", "before food": "a.c.",
               "with meals": "w/ meals", "bedtime": "qHS", "empty stomach": "on empty stomach"}
TIMING_IN = {"morning": "morning", "night": "at night", "after food": "after food", "before food": "before food",
             "with meals": "with food", "bedtime": "at bedtime", "empty stomach": "empty stomach"}
PER_DAY = {"once daily": 1, "twice daily": 2, "three times daily": 3, "at bedtime": 1}
FORM_PREFIX = {"tablet": "Tab.", "capsule": "Cap.", "injection": "Inj."}


def in_pattern(freq, timing):
    if freq == "twice daily":
        return "1-0-1"
    if freq == "three times daily":
        return "1-1-1"
    if freq == "at bedtime" or timing in ("bedtime", "night"):
        return "0-0-1"
    return "1-0-0"


def build_med(key, patient, region, rng, chronic, abbrev=False, acute_days=None, table=False):
    """Return (truth_dict, printed_name_line, printed_detail_line)."""
    d = DRUGS[key]
    opts = d.get("strength_in") if region == "IN" and d.get("strength_in") else d["strength"]
    strength = patient.strengths.setdefault(key, rng.choice(opts))
    use_generic = rng.random() < (0.75 if region == "US" else 0.25)
    generic = d.get("generic_in") if region == "IN" and d.get("generic_in") else d["generic"]
    name = generic if use_generic else rng.choice(d["us"] if region == "US" else d["inn"])
    form = d["form"]
    route = d.get("route", "oral")
    freq = "as needed" if d.get("as_needed") else d["freq"]
    timing = None if freq == "as needed" else d["timing"]

    # brand with strength baked into the name (Dolo 650, Pan 40)
    strength_in_name = name.split()[-1].isdigit()
    if strength_in_name:
        strength = f"{name.split()[-1]} mg"
    inj = form == "injection"
    dosage = strength if inj else f"1 {form}"
    truth_strength = None if inj else strength

    if freq == "as needed":
        duration = None
    elif freq == "weekly":
        duration = "8 weeks"
    elif chronic:
        duration = rng.choice(["30 days", "60 days", "90 days"])
    else:
        duration = f"{acute_days or rng.randint(3, 7)} days"

    truth = dict(name=name, generic_name=generic.lower(), strength=truth_strength, dosage=dosage,
                 frequency=freq, timing=timing, route=route, duration=duration,
                 generic_printed=use_generic,
                 # what the document actually prints (extractors must not be scored on invisible info):
                 duration_printed=(region == "IN" or table),      # US sigs print only "Disp: #N"
                 dosage_printed=(inj or (region == "US" and not table)),   # IN "1-0-1" and discharge tables never say "1 tablet"
                 route_printed=(not table))                       # discharge tables print no route

    name_bits = [name] if strength_in_name or inj else [name, strength]
    if region == "US":
        head = " ".join(name_bits + ([] if inj else [form]))
        if inj:
            head += " injection"
        if freq == "as needed":
            sig = f"Sig: Take 1 {form} by mouth every 6 hours as needed for pain or fever."
            if abbrev:
                sig = "Sig: 1 tab PO q6h PRN pain/fever"
            qty, refills = 20, 0
        elif inj:
            sig = f"Sig: Inject {strength} subcutaneously {FREQ_VERBOSE[freq]}."
            if abbrev:
                sig = f"Sig: {strength} SC {FREQ_ABBR[freq]}"
            qty, refills = "1 pen", 3
        else:
            days = int(duration.split()[0]) if duration and duration.endswith("days") else 56
            qty = PER_DAY.get(freq, 1) * days if freq != "weekly" else 8
            refills = rng.randint(1, 3) if chronic else 0
            if abbrev:
                sig = f"Sig: 1 {'tab' if form == 'tablet' else 'cap'} PO {FREQ_ABBR[freq]}"
                if timing and freq != "at bedtime":
                    sig += f" {TIMING_ABBR[timing]}"
            else:
                sig = f"Sig: Take 1 {form} by mouth {FREQ_VERBOSE[freq]}"
                if timing and freq != "at bedtime":
                    sig += f" {TIMING_US[timing]}"
                sig += "."
        detail = f"{sig}   Disp: #{qty}   Refills: {refills}"
        truth.update(quantity=qty, refills=refills, instructions=sig.replace("Sig: ", ""))
        return truth, head, detail

    # India
    head = f"{FORM_PREFIX[form]} " + " ".join(name_bits)
    if freq == "as needed":
        detail = "SOS (if fever / body pain)"
    elif inj:
        detail = f"{strength} SC at bedtime   x {duration}"
    elif freq == "weekly":
        detail = f"once a week, {TIMING_IN[timing]}   x {duration}"
    else:
        detail = f"{in_pattern(freq, timing)}   {TIMING_IN[timing]}   x {duration}"
    truth["instructions"] = detail
    return truth, head, detail


def usable(keys, patient):
    out = []
    for k in keys:
        if patient.allergy and patient.allergy.startswith("Penicillin") and k == "amox_clav":
            k = "azithromycin"
        if k not in out:
            out.append(k)
    return out


# ══════════════════════════════════════════════════════════════════════
#  Labs
# ══════════════════════════════════════════════════════════════════════
COND_PANELS = {"t2dm": ["diabetes", "lipid", "renal"], "htn": ["renal", "lipid"], "hypothyroid": ["thyroid"],
               "hld": ["lipid"], "anemia": ["cbc", "vitamins"], "gerd": ["cbc", "liver"], "vitd_def": ["vitamins"]}
SPECIMEN = {"cbc": "EDTA Whole Blood", "diabetes": "Fluoride Plasma", "hba1c": "EDTA Whole Blood"}


def lab_range(spec, sex):
    return spec[sex] if isinstance(spec, dict) else spec


def fmtn(x, dec):
    return f"{x:.{dec}f}"


def ref_string(rng_, dec):
    lo, hi = rng_
    if lo is None:
        return f"<{fmtn(hi, dec)}"
    if hi is None:
        return f">{fmtn(lo, dec)}"
    return f"{fmtn(lo, dec)}-{fmtn(hi, dec)}"


def gen_positions(keys, patient, rng, extra_bias=None):
    bias = {}
    for c in patient.conds:
        for k, u in CONDITIONS[c]["bias"].items():
            bias[k] = u
    bias.update(extra_bias or {})
    pos = {}
    for k in keys:
        if k in bias:
            pos[k] = rng.gauss(bias[k], 0.25 if bias[k] > 0.3 else 0.1)
        else:
            u = rng.gauss(0.5, 0.17)
            if rng.random() < 0.08:
                u = rng.choice([-0.25, 1.3])
            pos[k] = u
    return pos


def make_lab_row(key, u, region, sex):
    name, unit, spec, dec = LAB_BY_KEY[key][region]
    lo, hi = lab_range(spec, sex)
    lo_e = lo if lo is not None else hi * 0.4
    hi_e = hi if hi is not None else lo * 2.0
    v = max(lo_e + (hi_e - lo_e) * u, 0.05 * hi_e)
    v = round(v, dec)
    flag = None
    if lo is not None and v < lo:
        flag = "L"
    if hi is not None and v > hi:
        flag = "H"
    return dict(test_name=name, test_value=fmtn(v, dec), numeric_value=v, unit=unit,
                reference_range=ref_string((lo, hi), dec), is_abnormal=flag is not None, flag=flag, key=key)


def choose_panels(patient, rng):
    pool = []
    for c in patient.conds:
        pool += COND_PANELS.get(c, [])
    pool = list(dict.fromkeys(pool))
    rng.shuffle(pool)
    panels = pool[: rng.randint(1, 3)]
    if rng.random() < 0.5 and "cbc" not in panels:
        panels.insert(0, "cbc")
    return panels or ["cbc", "lipid"]


# ══════════════════════════════════════════════════════════════════════
#  Rendering helpers
# ══════════════════════════════════════════════════════════════════════
class Style:
    def __init__(self, region, rng):
        self.region = region
        self.font, self.bold = rng.choice(FONT_FAMILIES)
        self.color = rng.choice(PALETTES)
        self.center = rng.random() < 0.5
        self.datefmt = pick_datefmt(region, rng)
        self.page = letter if region == "US" else A4
        self.margin = rng.choice([14, 16, 18]) * mm
        self.size = rng.choice([9, 9.5, 10])

    def p(self, name, **kw):
        base = dict(fontName=self.font, fontSize=self.size, leading=self.size * 1.3, textColor=colors.black)
        base.update(kw)
        return ParagraphStyle(name, **base)


def header_block(st, title, lines, rng, right_lines=None):
    al = TA_CENTER if st.center else TA_LEFT
    parts = [Paragraph(esc(title), st.p("h", fontName=st.bold, fontSize=st.size + 6, leading=st.size + 9,
                                        textColor=st.color, alignment=al))]
    for ln in lines:
        parts.append(Paragraph(esc(ln), st.p("hl", fontSize=st.size - 1, leading=st.size + 2,
                                             textColor=colors.HexColor("#444444"), alignment=al)))
    parts.append(Spacer(1, 3))
    parts.append(HRFlowable(width="100%", thickness=1.4, color=st.color))
    parts.append(Spacer(1, 6))
    return parts


def kv_table(st, rows, cols=2, widths=None):
    """rows: list of (label, value); laid out `cols` pairs per row."""
    lab = st.p("lab", fontName=st.bold, fontSize=st.size - 0.5)
    val = st.p("val", fontSize=st.size)
    data = []
    for i in range(0, len(rows), cols):
        row = []
        for lbl, v in rows[i:i + cols]:
            row += [Paragraph(esc(lbl), lab), Paragraph(esc(v), val)]
        row += [""] * (cols * 2 - len(row))
        data.append(row)
    t = Table(data, colWidths=widths)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("LEFTPADDING", (0, 0), (-1, -1), 3),
                           ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#999999")),
                           ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f6f6"))]))
    return t


def build_pdf(path, story, st, watermark):
    def footer(canvas, doc):
        canvas.saveState()
        if watermark:
            canvas.setFont("Helvetica", 6.5)
            canvas.setFillColor(colors.HexColor("#999999"))
            canvas.drawCentredString(st.page[0] / 2, 8 * mm, WATERMARK)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawRightString(st.page[0] - st.margin, 12 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(path, pagesize=st.page, leftMargin=st.margin, rightMargin=st.margin,
                            topMargin=st.margin, bottomMargin=18 * mm)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def allergy_parts(patient):
    if not patient.allergy:
        return "NKDA (no known drug allergies)", []
    a, r = patient.allergy.split("|")
    return f"{a} ({r})", [dict(allergen=a, reaction=r)]


# ══════════════════════════════════════════════════════════════════════
#  Document builders — each returns (story, st, expected, meta)
# ══════════════════════════════════════════════════════════════════════
def follow_up(date, rng, fmt, region):
    """Returns (iso_date | None, printed_text, relative_text | None)."""
    days = rng.choice([7, 14, 14, 28, 30, 60, 90])
    d = date + dt.timedelta(days=days)
    if rng.random() < 0.25:
        rel = {7: "1 week", 14: "2 weeks", 28: "4 weeks", 30: "1 month", 60: "2 months", 90: "3 months"}[days]
        return None, f"Review after {rel}" if region == "IN" else f"Follow up in {rel}", rel
    label = "Next visit on" if region == "IN" else "Follow-up appointment:"
    return d.isoformat(), f"{label} {fd(d, fmt)}", None


def doc_prescription(patient, region, rng, fk, date):
    st = Style(region, rng)
    doctor = make_doctor(region, rng, fk)
    handwritten = region == "IN" and HAND_FONT is not None and rng.random() < 0.5
    abbrev = region == "US" and rng.random() < 0.4
    clinic = rng.choice(CLINICS[region]).format(last=doctor.last)

    # clinical content
    if rng.random() < 0.7:
        c = rng.choice(patient.conds)
        cond = CONDITIONS[c]
        keys = list(cond["meds"]) + rng.sample(cond["extra"], k=min(len(cond["extra"]), rng.randint(0, 1)))
        dx_name, icd, chronic, days = cond["name"], cond["icd"], True, None
        if len(patient.conds) > 1 and rng.random() < 0.4:
            other = CONDITIONS[rng.choice([x for x in patient.conds if x != c])]
            keys.append(other["meds"][0])
    else:
        a = ACUTE[rng.choice(list(ACUTE))]
        keys = list(a["meds"])
        dx_name, icd, chronic, days = a["name"], a["icd"], False, rng.randint(*a["days"])
    keys = usable(keys, patient)

    meds, med_lines = [], []
    for k in keys:
        t, head, detail = build_med(k, patient, region, rng, chronic, abbrev, days)
        meds.append(t)
        med_lines.append((head, detail))

    fu_iso, fu_text, fu_rel = follow_up(date, rng, st.datefmt, region)
    allergy_txt, allergies = allergy_parts(patient)

    # header
    if region == "US":
        lines = [patient_addr_clinic(rng, fk), f"Tel: ({rng.randint(201, 989)}) {rng.randint(200, 999)}-{rng.randint(1000, 9999)}"]
        title = clinic
        sub = [f"{doctor.name}, {doctor.quals}", f"{doctor.reg}    {doctor.extra}"] + lines
    else:
        title = clinic
        sub = [f"{doctor.name}  ({doctor.quals})", doctor.reg, patient_addr_clinic(rng, fk),
               f"Ph: +91 {rng.choice('6789')}{rng.randint(10**8, 10**9 - 1)}   |   Timings: 10 AM - 1 PM, 5 PM - 8 PM"]
    story = header_block(st, title, sub, rng)

    age_sex = f"{patient.age} / {patient.sex}" if region == "IN" else f"{patient.age} y, {'Male' if patient.sex == 'M' else 'Female'}"
    rows = [("Patient:", patient.name), ("Date:", fd(date, st.datefmt)),
            ("Age/Sex:" if region == "IN" else "Age/Sex:", age_sex),
            ("DOB:" if region == "US" else "Phone:", fd(patient.dob, st.datefmt) if region == "US" else patient.phone)]
    story += [kv_table(st, rows), Spacer(1, 6)]

    body_font = HAND_FONT if handwritten else st.font
    ink = colors.HexColor("#1b2a6b") if handwritten else colors.black
    bsz = 13 if handwritten else st.size + 0.5
    story.append(Paragraph(f"<b>Dx:</b> {esc(dx_name)}" + (f"  ({icd})" if region == "US" else ""),
                           st.p("dx", fontName=body_font, fontSize=bsz, leading=bsz * 1.35, textColor=ink)))
    story.append(Paragraph(f"<b>Allergies:</b> {esc(allergy_txt)}", st.p("al", fontName=body_font, fontSize=bsz,
                                                                         leading=bsz * 1.35, textColor=ink)))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Rx", st.p("rx", fontName=st.bold, fontSize=22, leading=28, spaceAfter=6, textColor=st.color)))
    for i, (head, detail) in enumerate(med_lines, 1):
        story.append(Paragraph(f"{i}) <b>{esc(head)}</b>", st.p("m1", fontName=body_font, fontSize=bsz + 0.5,
                                                               leading=bsz * 1.4, textColor=ink, leftIndent=8)))
        story.append(Paragraph(esc(detail), st.p("m2", fontName=body_font, fontSize=bsz - 0.5, leading=bsz * 1.3,
                                                 textColor=ink, leftIndent=26)))
        story.append(Spacer(1, 4))
    story.append(Spacer(1, 6))
    advice = rng.choice(["Plenty of oral fluids. Avoid oily / spicy food.", "Low salt, low sugar diet. Walk 30 min daily.",
                         "Adequate rest. Return if symptoms worsen.", "Continue home BP / sugar monitoring."])
    story.append(Paragraph(f"<b>Advice:</b> {esc(advice)}", st.p("ad", fontName=body_font, fontSize=bsz,
                                                                 leading=bsz * 1.35, textColor=ink)))
    story.append(Paragraph(esc(fu_text), st.p("fu", fontName=body_font, fontSize=bsz, leading=bsz * 1.35, textColor=ink)))
    story.append(Spacer(1, 30))
    sig_font = HAND_FONT or "Helvetica-Oblique"
    story.append(Paragraph(esc(doctor.last), st.p("sig", fontName=sig_font, fontSize=18, leading=24, spaceAfter=4,
                                                   alignment=TA_RIGHT, textColor=colors.HexColor("#1b2a6b"))))
    story.append(Paragraph(esc(doctor.name), st.p("sn", alignment=TA_RIGHT, fontSize=st.size - 1)))

    expected = dict(category="prescription", document_date=date.isoformat(), doctor=doctor.name, hospital=clinic,
                    patient_name=patient.name, medications=meds, lab_results=[], diagnoses=[dx_name],
                    allergies=allergies, follow_up_date=fu_iso)
    meta = dict(template=f"rx_{region.lower()}", handwritten_font=handwritten, abbreviated_sig=abbrev,
                follow_up_relative=fu_rel, printed_date_format=st.datefmt, font=st.font)
    return story, st, expected, meta


def patient_addr_clinic(rng, fk):
    return fk.address().replace("\n", ", ")


def doc_lab_report(patient, region, rng, fk, date, panels=None, positions=None):
    st = Style(region, rng)
    doctor = make_doctor(region, rng, fk)
    lab = rng.choice(LABS_NAMES[region])
    panels = panels or choose_panels(patient, rng)
    keys = [l["key"] for p in panels for l in LABS if l["panel"] == p and region in l]
    pos = positions or gen_positions(keys, patient, rng)
    rows_by_panel = {p: [make_lab_row(l["key"], pos[l["key"]], region, patient.sex)
                         for l in LABS if l["panel"] == p] for p in panels}
    collected = date - dt.timedelta(days=rng.choice([0, 0, 1]))
    acc = f"{rng.choice('ABCDEFGH')}{rng.randint(10**7, 10**8 - 1)}"

    if region == "US":
        sub = [patient_addr_clinic(rng, fk), f"CLIA #: {rng.randint(10, 99)}D{rng.randint(10**6, 10**7 - 1)}   "
                                             f"Lab Director: {fk.name()}, MD"]
        story = header_block(st, lab, sub, rng)
        info = [("Patient:", patient.name), ("DOB:", fd(patient.dob, st.datefmt)),
                ("Sex:", "Male" if patient.sex == "M" else "Female"), ("Patient ID:", patient.pid),
                ("Ordering Provider:", doctor.name + ", " + doctor.quals), ("Accession #:", acc),
                ("Collected:", fd(collected, st.datefmt)), ("Reported:", fd(date, st.datefmt))]
        cols = ["Test", "Result", "Flag", "Reference Range", "Units"]
    else:
        sub = [patient_addr_clinic(rng, fk), f"NABL Accredited  |  Lab ID: {rng.randint(10**4, 10**5)}  |  "
                                             f"Ph: +91 {rng.randint(10**9, 10**10 - 1)}"]
        story = header_block(st, lab, sub, rng)
        info = [("Name:", patient.name), ("Age / Sex:", f"{patient.age} Years / {'Male' if patient.sex == 'M' else 'Female'}"),
                ("Patient ID:", patient.pid), ("Sample ID:", acc),
                ("Referred By:", doctor.name), ("Sample Collected:", fd(collected, st.datefmt)),
                ("Reported On:", fd(date, st.datefmt)), ("Phone:", patient.phone)]
        cols = ["Test Name", "Result", "Unit", "Biological Ref. Interval"]
    story += [kv_table(st, info), Spacer(1, 8)]

    cell = st.p("c", fontSize=st.size - 0.5)
    cellb = st.p("cb", fontName=st.bold, fontSize=st.size - 0.5, textColor=colors.HexColor("#b00020"))
    head = st.p("th", fontName=st.bold, fontSize=st.size - 0.5, textColor=colors.white)
    truth_labs = []
    W = st.page[0] - 2 * st.margin
    for p in panels:
        story.append(Paragraph(esc(PANELS[p][region]), st.p("pt", fontName=st.bold, fontSize=st.size + 1.5,
                                                            textColor=st.color, spaceBefore=6, spaceAfter=3)))
        data = [[Paragraph(c, head) for c in cols]]
        for r in rows_by_panel[p]:
            sty = cellb if r["is_abnormal"] else cell
            val = f"<b>{r['test_value']}</b>" if r["is_abnormal"] else r["test_value"]
            if region == "US":
                data.append([Paragraph(esc(r["test_name"]), cell), Paragraph(val, sty),
                             Paragraph(r["flag"] or "", sty), Paragraph(esc(r["reference_range"]), cell),
                             Paragraph(esc(r["unit"]), cell)])
            else:
                mark = f" ({r['flag']})" if r["flag"] else ""
                data.append([Paragraph(esc(r["test_name"]), cell), Paragraph(val + mark, sty),
                             Paragraph(esc(r["unit"]), cell), Paragraph(esc(r["reference_range"]), cell)])
            truth_labs.append(dict(test_name=r["test_name"], test_value=r["test_value"], unit=r["unit"],
                                   reference_range=r["reference_range"], is_abnormal=r["is_abnormal"],
                                   flag=r["flag"], panel=PANELS[p][region],
                                   specimen_type=SPECIMEN.get(p, "Serum"), report_date=date.isoformat()))
        widths = [W * f for f in ([0.34, 0.14, 0.1, 0.24, 0.18] if region == "US" else [0.38, 0.17, 0.17, 0.28])]
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), st.color),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f3f3")]),
                               ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story.append(t)
    story.append(Spacer(1, 10))
    note = ("H = High, L = Low. Results should be interpreted in the clinical context." if region == "US"
            else "(H) = High, (L) = Low. *** End of Report *** Please correlate clinically.")
    story.append(Paragraph(esc(note), st.p("n", fontSize=st.size - 1.5, textColor=colors.HexColor("#555555"))))

    expected = dict(category="lab_report", document_date=date.isoformat(), doctor=doctor.name, hospital=lab,
                    patient_name=patient.name, medications=[], lab_results=truth_labs, diagnoses=[],
                    allergies=[], follow_up_date=None)
    meta = dict(template=f"lab_{region.lower()}", collection_date=collected.isoformat(),
                printed_date_format=st.datefmt, font=st.font, panels=panels)
    return story, st, expected, meta


def doc_discharge(patient, region, rng, fk, date):
    st = Style(region, rng)
    doctor = make_doctor(region, rng, fk)
    hospital = rng.choice(HOSPITALS[region])
    sc = rng.choice([s for s in SCENARIOS if region in s["regions"]])
    stay = rng.randint(*sc["stay"])
    admit = date - dt.timedelta(days=stay)
    keys = usable(sc["meds"], patient)
    home = [CONDITIONS[c]["meds"][0] for c in patient.conds if c != "gerd"][:1]
    for h in usable(home, patient):
        if h not in keys:
            keys.append(h)

    meds, rows = [], []
    for k in keys:
        chronic = DRUGS[k].get("chronic", False)
        t, head, detail = build_med(k, patient, region, rng, chronic, False, rng.randint(3, 7), table=True)
        meds.append(t)
        rows.append((head, t))

    lab_keys = [k for k in sc["bias"]] + rng.sample(["hemoglobin", "wbc", "creatinine", "sodium", "potassium"], 2)
    lab_keys = list(dict.fromkeys(lab_keys))
    pos = gen_positions(lab_keys, patient, rng, sc["bias"])
    lab_rows = [make_lab_row(k, pos[k], region, patient.sex) for k in lab_keys]
    fu_iso, fu_text, fu_rel = follow_up(date, rng, st.datefmt, region)
    allergy_txt, allergies = allergy_parts(patient)

    if region == "US":
        sub = [patient_addr_clinic(rng, fk), f"Tel: ({rng.randint(201, 989)}) {rng.randint(200, 999)}-{rng.randint(1000, 9999)}"]
        idl, enc = "MRN", f"Account #: {rng.randint(10**8, 10**9 - 1)}"
    else:
        sub = [patient_addr_clinic(rng, fk), f"Ph: +91 {rng.randint(10**9, 10**10 - 1)}   |   Emergency: 24x7"]
        idl, enc = "UHID", f"IP No.: IP/{rng.randint(2020, 2026)}/{rng.randint(1000, 99999)}"
    story = header_block(st, hospital, sub, rng)
    story.append(Paragraph("DISCHARGE SUMMARY", st.p("ds", fontName=st.bold, fontSize=st.size + 4, alignment=TA_CENTER,
                                                     textColor=st.color, spaceAfter=6)))
    info = [("Patient Name:", patient.name),
            ("Age / Sex:", f"{patient.age} / {'Male' if patient.sex == 'M' else 'Female'}"),
            (f"{idl}:", patient.pid), (enc.split(":")[0] + ":", enc.split(": ", 1)[1]),
            ("Date of Admission:", fd(admit, st.datefmt)), ("Date of Discharge:", fd(date, st.datefmt)),
            ("Attending Physician:" if region == "US" else "Consultant:", doctor.name),
            ("Department:", "Internal Medicine" if region == "US" else "General Medicine")]
    story += [kv_table(st, info), Spacer(1, 8)]

    def sec(title, text=None):
        story.append(Paragraph(esc(title), st.p("sec", fontName=st.bold, fontSize=st.size + 1, textColor=st.color,
                                                spaceBefore=7, spaceAfter=2)))
        if text:
            story.append(Paragraph(esc(text), st.p("tx", leading=st.size * 1.45)))

    sec("Final Diagnosis", f"{sc['dx']} ({sc['icd']})" if region == "US" else sc["dx"])
    if sc["procedure"]:
        sec("Procedure Performed", sc["procedure"])
    pmh = ", ".join(CONDITIONS[c]["name"] for c in patient.conds)
    sec("Past Medical History", f"{pmh}.   Allergies: {allergy_txt}.")
    sym = sc["sym"]
    pron = "He" if patient.sex == "M" else "She"
    sec("Brief History and Hospital Course",
        f"{patient.age}-year-old {'male' if patient.sex == 'M' else 'female'} {sc['course'].format(sym=sym)} "
        f"{pron} remained hemodynamically stable during the {stay}-day stay.")

    inv = "; ".join(f"{r['test_name']} {r['test_value']} {r['unit']}" for r in lab_rows)
    sec("Key Investigations", inv + ".")

    story.append(Paragraph("Medications on Discharge", st.p("sec2", fontName=st.bold, fontSize=st.size + 1,
                                                            textColor=st.color, spaceBefore=7, spaceAfter=3)))
    hd = st.p("th", fontName=st.bold, fontSize=st.size - 0.5, textColor=colors.white)
    cl = st.p("c", fontSize=st.size - 0.5)
    data = [[Paragraph(c, hd) for c in ["Medication", "Dose", "Frequency", "Duration"]]]
    for head_txt, t in rows:
        dose = t["dosage"] if t["dosage"] and t["route"] != "oral" else (t["strength"] or t["dosage"])
        freq = t["frequency"] + (f", {t['timing']}" if t["timing"] else "")
        data.append([Paragraph(esc(head_txt), cl), Paragraph(esc(dose), cl), Paragraph(esc(freq), cl),
                     Paragraph(esc(t["duration"] or "as needed"), cl)])
    W = st.page[0] - 2 * st.margin
    t = Table(data, colWidths=[W * 0.34, W * 0.16, W * 0.28, W * 0.22], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), st.color),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f3f3")]),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc"))]))
    story.append(t)

    sec("Condition at Discharge", "Stable, afebrile, tolerating oral diet, ambulatory.")
    sec("Follow-up and Advice", fu_text + ". Return to the emergency department for worsening symptoms. "
                                          "Maintain adequate hydration and follow the prescribed diet.")
    story.append(Spacer(1, 18))
    story.append(Paragraph(f"{esc(doctor.name)}, {esc(doctor.quals)}<br/>{esc(doctor.reg)}",
                           st.p("sg", alignment=TA_RIGHT)))

    for r in lab_rows:   # investigations printed without ranges
        r["range_printed"] = False
    truth_labs = [dict(test_name=r["test_name"], test_value=r["test_value"], unit=r["unit"], reference_range=None,
                       is_abnormal=None, flag=None, report_date=date.isoformat()) for r in lab_rows]
    expected = dict(category="discharge_summary", document_date=date.isoformat(), doctor=doctor.name,
                    hospital=hospital, patient_name=patient.name, medications=meds, lab_results=truth_labs,
                    diagnoses=[sc["dx"]], allergies=allergies, follow_up_date=fu_iso,
                    past_medical_history=[CONDITIONS[c]["name"] for c in patient.conds],
                    admission_date=admit.isoformat(), discharge_date=date.isoformat(),
                    procedures=[sc["procedure"]] if sc["procedure"] else [])
    meta = dict(template=f"discharge_{region.lower()}", follow_up_relative=fu_rel,
                printed_date_format=st.datefmt, font=st.font, scenario=sc["dx"])
    return story, st, expected, meta


BUILDERS = {"prescription": doc_prescription, "lab_report": doc_lab_report, "discharge_summary": doc_discharge}


# ══════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=60, help="total documents")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="output")
    ap.add_argument("--region", choices=["US", "IN", "both"], default="both")
    ap.add_argument("--mix", default="0.4,0.3,0.3", help="fractions: clean pdf, scan, phone photo")
    ap.add_argument("--no-watermark", action="store_true")
    ap.add_argument("--extra-labs", type=int, default=0,
                    help="extra clean lab reports per patient with drifting values (for trend charts); main set unchanged")
    ap.add_argument("--clean", action="store_true", help="delete the output dir first")
    a = ap.parse_args()

    if a.clean and os.path.isdir(a.out):
        shutil.rmtree(a.out)
    docs_dir, truth_dir = os.path.join(a.out, "documents"), os.path.join(a.out, "truth")
    os.makedirs(docs_dir, exist_ok=True)
    os.makedirs(truth_dir, exist_ok=True)
    register_fonts()

    rng = random.Random(a.seed)
    Faker.seed(a.seed)
    fk = {"US": Faker("en_US"), "IN": Faker("en_IN")}
    regions = ["US", "IN"] if a.region == "both" else [a.region]
    mix = [float(x) for x in a.mix.split(",")]
    cats = ["prescription", "lab_report", "discharge_summary"]

    patients, manifest = [], []
    n_patients = max(1, a.count // 3)
    counters = {}
    tmp = tempfile.mkdtemp(prefix="synth_")
    made = 0
    for pi in range(n_patients):
        region = regions[pi % len(regions)]
        pat = make_patient(pi + 1, region, rng, fk[region])
        patients.append(pat)
        # spread visits over the last ~18 months, oldest first
        dates = sorted(TODAY - dt.timedelta(days=rng.randint(5, 540)) for _ in range(3))
        order = cats[:]
        rng.shuffle(order)
        for cat, date in zip(order, dates):
            if made >= a.count:
                break
            n = counters.get((region, cat), 0) + 1
            counters[(region, cat)] = n
            doc_id = f"{region.lower()}_{cat}_{n:03d}"
            story, st, expected, meta = BUILDERS[cat](pat, region, rng, fk[region], date)

            pdf_path = os.path.join(tmp, doc_id + ".pdf")
            build_pdf(pdf_path, story, st, not a.no_watermark)

            mode = rng.choices(["clean", "scan", "photo"], mix)[0]
            files = []
            if mode == "clean":
                shutil.copy(pdf_path, os.path.join(docs_dir, doc_id + ".pdf"))
                files.append(doc_id + ".pdf")
                deg = None
            else:
                pages = degrade.pdf_to_images(pdf_path)
                for i, img in enumerate(pages, 1):
                    img, deg = (degrade.scan if mode == "scan" else degrade.photo)(img, rng)
                    fn = f"{doc_id}.jpg" if i == 1 else f"{doc_id}_p{i}.jpg"
                    degrade.save_jpeg(img, os.path.join(docs_dir, fn), deg["jpeg"])
                    files.append(fn)
            record = dict(id=doc_id, region=region, category=cat, patient_id=pat.id, files=files,
                          degradation=mode, degradation_params=deg, generation=meta, expected=expected)
            with open(os.path.join(truth_dir, doc_id + ".json"), "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2, ensure_ascii=False)
            manifest.append(dict(id=doc_id, region=region, category=cat, degradation=mode, files=files))
            pat.docs.append(doc_id)
            made += 1
            print(f"  [{made:3d}/{a.count}] {doc_id:28s} {mode:5s} {', '.join(files)}")

    # Extra lab reports whose values drift over time, so the Analytics page has real trends.
    # Uses its own RNG and runs after the main set, so the main documents are identical with or without it.
    if a.extra_labs:
        rng2 = random.Random(a.seed + 1000)
        for pat in patients:
            region = pat.region
            panels = []
            for c in pat.conds:
                panels += COND_PANELS.get(c, [])
            panels = list(dict.fromkeys(panels))[:3] or ["cbc", "lipid"]
            keys = [l["key"] for p in panels for l in LABS if l["panel"] == p and region in l]
            base = gen_positions(keys, pat, rng2)
            drift = {k: rng2.uniform(-0.6, 0.6) for k in keys}
            n_extra = a.extra_labs
            days = rng2.sample(range(10, 560), n_extra)
            for j, date in enumerate(sorted((TODAY - dt.timedelta(days=d) for d in days))):
                frac = (j / (n_extra - 1) - 0.5) if n_extra > 1 else 0.0
                pos = {k: base[k] + drift[k] * frac + rng2.gauss(0, 0.07) for k in keys}
                cnt = counters.get((region, "lab_report"), 0) + 1
                counters[(region, "lab_report")] = cnt
                doc_id = f"{region.lower()}_lab_report_{cnt:03d}"
                story, st, expected, meta = doc_lab_report(pat, region, rng2, fk[region], date, panels=panels, positions=pos)
                build_pdf(os.path.join(docs_dir, doc_id + ".pdf"), story, st, not a.no_watermark)
                record = dict(id=doc_id, region=region, category="lab_report", patient_id=pat.id,
                              files=[doc_id + ".pdf"], degradation="clean", degradation_params=None,
                              generation=dict(meta, extra_trend=True), expected=expected)
                with open(os.path.join(truth_dir, doc_id + ".json"), "w", encoding="utf-8") as f:
                    json.dump(record, f, indent=2, ensure_ascii=False)
                manifest.append(dict(id=doc_id, region=region, category="lab_report", degradation="clean",
                                     files=record["files"]))
                pat.docs.append(doc_id)
                made += 1
        print(f"  + {a.extra_labs} extra trending lab reports per patient")

    shutil.rmtree(tmp, ignore_errors=True)
    with open(os.path.join(a.out, "manifest.jsonl"), "w", encoding="utf-8") as f:
        for m in manifest:
            f.write(json.dumps(m) + "\n")
    with open(os.path.join(a.out, "patients.json"), "w", encoding="utf-8") as f:
        json.dump([dict(id=p.id, region=p.region, name=p.name, sex=p.sex, age=p.age, dob=p.dob.isoformat(),
                        patient_ref=p.pid, phone=p.phone, address=p.address,
                        conditions=[CONDITIONS[c]["name"] for c in p.conds],
                        allergy=p.allergy, documents=p.docs) for p in patients], f, indent=2, ensure_ascii=False)
    print(f"\nDone: {made} documents, {len(patients)} patients -> {os.path.abspath(a.out)}")


if __name__ == "__main__":
    main()
