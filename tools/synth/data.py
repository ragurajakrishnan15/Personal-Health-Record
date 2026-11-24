"""Reference data for the synthetic medical-document generator.

Everything here is fictional or generic. Hospital/clinic/lab names are invented.
Lab values are generated from a position `u` inside the reference range
(0 = lower bound, 1 = upper bound, <0 / >1 = abnormal), so the same underlying
patient state renders consistently in US and Indian units/ranges.
"""

# ── Labs ──────────────────────────────────────────────────────────────
# range spec: (low, high) | {"M": (low, high), "F": (low, high)}; None = one-sided.
# region tuple: (printed name, unit, range spec, decimals)
LABS = [
    dict(key="hemoglobin", panel="cbc",
         US=("Hemoglobin", "g/dL", {"M": (13.5, 17.5), "F": (12.0, 15.5)}, 1),
         IN=("Haemoglobin", "g/dL", {"M": (13.0, 17.0), "F": (12.0, 15.0)}, 1)),
    dict(key="wbc", panel="cbc",
         US=("WBC Count", "10^3/uL", (4.5, 11.0), 1),
         IN=("Total Leucocyte Count", "cells/cumm", (4000, 11000), 0)),
    dict(key="platelets", panel="cbc",
         US=("Platelet Count", "10^3/uL", (150, 400), 0),
         IN=("Platelet Count", "lakhs/cumm", (1.5, 4.1), 2)),
    dict(key="hematocrit", panel="cbc",
         US=("Hematocrit", "%", {"M": (41, 53), "F": (36, 46)}, 1),
         IN=("PCV", "%", {"M": (40, 50), "F": (36, 46)}, 1)),

    dict(key="chol", panel="lipid",
         US=("Total Cholesterol", "mg/dL", (None, 200), 0),
         IN=("Total Cholesterol", "mg/dL", (None, 200), 0)),
    dict(key="ldl", panel="lipid",
         US=("LDL Cholesterol", "mg/dL", (None, 100), 0),
         IN=("LDL Cholesterol", "mg/dL", (None, 100), 0)),
    dict(key="hdl", panel="lipid",
         US=("HDL Cholesterol", "mg/dL", (40, None), 0),
         IN=("HDL Cholesterol", "mg/dL", (40, None), 0)),
    dict(key="tg", panel="lipid",
         US=("Triglycerides", "mg/dL", (None, 150), 0),
         IN=("Triglycerides", "mg/dL", (None, 150), 0)),

    dict(key="glucose", panel="diabetes",
         US=("Glucose, Fasting", "mg/dL", (70, 99), 0),
         IN=("Fasting Blood Sugar", "mg/dL", (70, 100), 0)),
    dict(key="hba1c", panel="diabetes",
         US=("Hemoglobin A1c", "%", (4.0, 5.6), 1),
         IN=("Glycosylated Hemoglobin (HbA1c)", "%", (4.0, 5.6), 1)),

    dict(key="creatinine", panel="renal",
         US=("Creatinine", "mg/dL", {"M": (0.74, 1.35), "F": (0.59, 1.04)}, 2),
         IN=("Serum Creatinine", "mg/dL", {"M": (0.7, 1.3), "F": (0.6, 1.1)}, 2)),
    dict(key="bun", panel="renal",
         US=("Blood Urea Nitrogen (BUN)", "mg/dL", (7, 20), 0),
         IN=("Blood Urea", "mg/dL", (15, 40), 0)),
    dict(key="sodium", panel="renal",
         US=("Sodium", "mmol/L", (135, 145), 0),
         IN=("Sodium", "mmol/L", (135, 145), 0)),
    dict(key="potassium", panel="renal",
         US=("Potassium", "mmol/L", (3.5, 5.0), 1),
         IN=("Potassium", "mmol/L", (3.5, 5.1), 1)),

    dict(key="alt", panel="liver",
         US=("ALT (SGPT)", "U/L", (7, 55), 0),
         IN=("SGPT (ALT)", "U/L", (5, 40), 0)),
    dict(key="ast", panel="liver",
         US=("AST (SGOT)", "U/L", (8, 48), 0),
         IN=("SGOT (AST)", "U/L", (5, 40), 0)),
    dict(key="bilirubin", panel="liver",
         US=("Bilirubin, Total", "mg/dL", (0.1, 1.2), 1),
         IN=("Total Bilirubin", "mg/dL", (0.2, 1.2), 1)),
    dict(key="alp", panel="liver",
         US=("Alkaline Phosphatase", "U/L", (40, 129), 0),
         IN=("Alkaline Phosphatase", "U/L", (44, 147), 0)),

    dict(key="tsh", panel="thyroid",
         US=("TSH", "mIU/L", (0.40, 4.00), 2),
         IN=("TSH (Ultrasensitive)", "uIU/mL", (0.35, 5.50), 2)),

    dict(key="vitd", panel="vitamins",
         US=("Vitamin D, 25-Hydroxy", "ng/mL", (30, 100), 1),
         IN=("Vitamin D (25-OH)", "ng/mL", (30, 100), 1)),
    dict(key="b12", panel="vitamins",
         US=("Vitamin B12", "pg/mL", (200, 900), 0),
         IN=("Vitamin B12", "pg/mL", (211, 911), 0)),
]
LAB_BY_KEY = {l["key"]: l for l in LABS}

PANELS = {
    "cbc": {"US": "Complete Blood Count (CBC)", "IN": "Complete Blood Count (CBC)"},
    "lipid": {"US": "Lipid Panel", "IN": "Lipid Profile"},
    "diabetes": {"US": "Glucose / Hemoglobin A1c", "IN": "Diabetes Screening"},
    "renal": {"US": "Basic Metabolic Panel", "IN": "Kidney Function Test (KFT)"},
    "liver": {"US": "Hepatic Function Panel", "IN": "Liver Function Test (LFT)"},
    "thyroid": {"US": "Thyroid Panel", "IN": "Thyroid Profile"},
    "vitamins": {"US": "Vitamins", "IN": "Vitamin Profile"},
}

# ── Drugs ─────────────────────────────────────────────────────────────
# freq: once daily | twice daily | three times daily | at bedtime | weekly
# timing: morning | night | after food | before food | with meals | bedtime | empty stomach
DRUGS = {
    "metformin": dict(generic="Metformin", us=["Glucophage"], inn=["Glycomet", "Obimet"],
                      strength=["500 mg", "850 mg", "1000 mg"], form="tablet", freq="twice daily",
                      timing="with meals", chronic=True),
    "glimepiride": dict(generic="Glimepiride", us=["Amaryl"], inn=["Amaryl", "Glimestar"],
                        strength=["1 mg", "2 mg"], form="tablet", freq="once daily",
                        timing="before food", chronic=True),
    "insulin_glargine": dict(generic="Insulin Glargine", us=["Lantus"], inn=["Basalog", "Lantus"],
                             strength=["10 units", "14 units", "20 units"], form="injection",
                             freq="at bedtime", timing="bedtime", chronic=True, route="subcutaneous"),
    "amlodipine": dict(generic="Amlodipine", us=["Norvasc"], inn=["Amlokind", "Amlong"],
                       strength=["5 mg", "10 mg"], form="tablet", freq="once daily",
                       timing="morning", chronic=True),
    "losartan": dict(generic="Losartan", us=["Cozaar"], inn=["Losar", "Repace"],
                     strength=["25 mg", "50 mg", "100 mg"], form="tablet", freq="once daily",
                     timing="morning", chronic=True),
    "atorvastatin": dict(generic="Atorvastatin", us=["Lipitor"], inn=["Atorva", "Storvas"],
                         strength=["10 mg", "20 mg", "40 mg"], form="tablet", freq="once daily",
                         timing="bedtime", chronic=True),
    "levothyroxine": dict(generic="Levothyroxine", us=["Synthroid"], inn=["Thyronorm", "Eltroxin"],
                          strength=["25 mcg", "50 mcg", "75 mcg", "100 mcg"], form="tablet",
                          freq="once daily", timing="empty stomach", chronic=True),
    "pantoprazole": dict(generic="Pantoprazole", us=["Protonix"], inn=["Pantop", "Pan 40"],
                         strength=["40 mg"], form="tablet", freq="once daily",
                         timing="before food", chronic=False),
    "omeprazole": dict(generic="Omeprazole", us=["Prilosec"], inn=["Omez", "Omecip"],
                       strength=["20 mg", "40 mg"], form="capsule", freq="once daily",
                       timing="before food", chronic=False),
    "paracetamol": dict(generic="Paracetamol", us=["Tylenol"], inn=["Dolo 650", "Crocin"],
                        strength=["500 mg", "650 mg"], form="tablet", freq="three times daily",
                        timing="after food", chronic=False, as_needed=True),
    "azithromycin": dict(generic="Azithromycin", us=["Zithromax"], inn=["Azithral", "Azee"],
                         strength=["250 mg", "500 mg"], form="tablet", freq="once daily",
                         timing="after food", chronic=False),
    "amox_clav": dict(generic="Amoxicillin-Clavulanate", us=["Augmentin"], inn=["Augmentin", "Clavam"],
                      strength=["625 mg", "875 mg"], strength_in=["625 mg"], form="tablet", freq="twice daily",
                      timing="after food", chronic=False),
    "cetirizine": dict(generic="Cetirizine", us=["Zyrtec"], inn=["Okacet", "Cetzine"],
                       strength=["10 mg"], form="tablet", freq="at bedtime",
                       timing="bedtime", chronic=False),
    "ondansetron": dict(generic="Ondansetron", us=["Zofran"], inn=["Emeset", "Ondem"],
                        strength=["4 mg", "8 mg"], form="tablet", freq="three times daily",
                        timing="before food", chronic=False),
    "ferrous": dict(generic="Ferrous Sulfate", generic_in="Ferrous Ascorbate", us=["Feosol"], inn=["Ferium", "Orofer"],
                    strength=["325 mg", "100 mg"], strength_in=["100 mg"], form="tablet", freq="once daily",
                    timing="after food", chronic=True),
    "vitd3": dict(generic="Cholecalciferol", us=["Vitamin D3"], inn=["Uprise-D3", "D-Rise"],
                  strength=["60000 IU", "2000 IU"], form="capsule", freq="weekly",
                  timing="after food", chronic=True),
    "metoprolol": dict(generic="Metoprolol", us=["Lopressor"], inn=["Metolar", "Betaloc"],
                       strength=["25 mg", "50 mg"], form="tablet", freq="twice daily",
                       timing="after food", chronic=True),
}

# ── Conditions ────────────────────────────────────────────────────────
# bias: lab key -> mean position u in reference range (sd 0.25 unless noted)
CONDITIONS = {
    "t2dm": dict(name="Type 2 diabetes mellitus", icd="E11.9", meds=["metformin"], extra=["glimepiride"],
                 bias={"hba1c": 2.3, "glucose": 2.6, "tg": 1.3}),
    "htn": dict(name="Essential hypertension", icd="I10", meds=["amlodipine"], extra=["losartan", "metoprolol"],
                bias={"potassium": 0.6, "creatinine": 0.7}),
    "hypothyroid": dict(name="Hypothyroidism", icd="E03.9", meds=["levothyroxine"], extra=[],
                        bias={"tsh": 1.9}),
    "hld": dict(name="Hyperlipidemia", icd="E78.5", meds=["atorvastatin"], extra=[],
                bias={"chol": 1.5, "ldl": 1.9, "tg": 1.5, "hdl": -0.2}),
    "anemia": dict(name="Iron deficiency anemia", icd="D50.9", meds=["ferrous"], extra=[],
                   bias={"hemoglobin": -0.45, "hematocrit": -0.4}),
    "gerd": dict(name="Gastro-esophageal reflux disease", icd="K21.9", meds=["pantoprazole"], extra=["omeprazole"],
                 bias={}),
    "vitd_def": dict(name="Vitamin D deficiency", icd="E55.9", meds=["vitd3"], extra=[],
                     bias={"vitd": -0.2, "b12": 0.1}),
}
# Indian patients: higher odds of vit-D deficiency / anemia; US: hld/htn.
COND_WEIGHTS = {
    "US": {"t2dm": 3, "htn": 5, "hypothyroid": 2, "hld": 4, "anemia": 1, "gerd": 3, "vitd_def": 1},
    "IN": {"t2dm": 5, "htn": 3, "hypothyroid": 3, "hld": 2, "anemia": 3, "gerd": 2, "vitd_def": 4},
}

ACUTE = {
    "urti": dict(name="Acute upper respiratory tract infection", icd="J06.9",
                 meds=["azithromycin", "cetirizine", "paracetamol"], days=(3, 5)),
    "viral_fever": dict(name="Viral fever", icd="B34.9",
                        meds=["paracetamol", "cetirizine"], days=(3, 5)),
}

# Discharge scenarios: region = allowed regions
SCENARIOS = [
    dict(dx="Community-acquired pneumonia", icd="J18.9", regions=("US", "IN"), stay=(3, 6),
         meds=["amox_clav", "azithromycin", "paracetamol"], bias={"wbc": 1.8},
         course="presented with {sym}. Chest imaging showed right lower lobe consolidation. "
                "Started on intravenous antibiotics with good clinical response, then stepped down to oral therapy.",
         sym="fever, productive cough and shortness of breath for 4 days", procedure=None),
    dict(dx="Acute gastroenteritis with dehydration", icd="A09", regions=("US", "IN"), stay=(2, 3),
         meds=["ondansetron", "pantoprazole"], bias={"potassium": -0.15, "sodium": 0.0},
         course="presented with {sym}. Managed with intravenous fluids, electrolyte correction and antiemetics. "
                "Tolerating oral diet at discharge.",
         sym="vomiting and loose stools for 2 days", procedure=None),
    dict(dx="Type 2 diabetes mellitus with hyperglycemia", icd="E11.65", regions=("US", "IN"), stay=(3, 5),
         meds=["insulin_glargine", "metformin"], bias={"glucose": 4.5, "hba1c": 3.2},
         course="presented with {sym}. Blood glucose was markedly elevated without ketosis. "
                "Basal insulin initiated and titrated; diabetic diet counselling given.",
         sym="polyuria, polydipsia and fatigue for 1 week", procedure=None),
    dict(dx="Dengue fever", icd="A90", regions=("IN",), stay=(3, 5),
         meds=["paracetamol"], bias={"platelets": -0.25, "wbc": -0.1, "hematocrit": 1.1},
         course="presented with {sym}. NS1 antigen positive. Managed with IV fluids and daily platelet monitoring; "
                "platelet count recovered before discharge.",
         sym="high-grade fever, body ache and headache for 4 days", procedure=None),
    dict(dx="Hypertensive urgency", icd="I16.0", regions=("US",), stay=(1, 3),
         meds=["amlodipine", "losartan"], bias={"creatinine": 1.3, "potassium": 0.9},
         course="presented with {sym}. Blood pressure on arrival 192/108 mmHg without end-organ damage. "
                "Gradually lowered with oral agents; home regimen adjusted.",
         sym="severe headache and elevated home blood pressure readings", procedure=None),
    dict(dx="Acute appendicitis", icd="K35.80", regions=("US", "IN"), stay=(2, 4),
         meds=["amox_clav", "paracetamol", "pantoprazole"], bias={"wbc": 1.7},
         course="presented with {sym}. Ultrasound and CT consistent with acute appendicitis. "
                "Underwent laparoscopic appendectomy without complications. Recovery uneventful.",
         sym="right lower quadrant abdominal pain and nausea for 24 hours",
         procedure="Laparoscopic appendectomy"),
    dict(dx="Typhoid (enteric) fever", icd="A01.00", regions=("IN",), stay=(4, 6),
         meds=["azithromycin", "paracetamol"], bias={"wbc": -0.1, "alt": 1.4, "ast": 1.3},
         course="presented with {sym}. Blood culture grew Salmonella typhi. Treated with antibiotics and supportive care; "
                "afebrile for 48 hours prior to discharge.",
         sym="step-ladder fever and abdominal discomfort for 6 days", procedure=None),
]

# ── Places & people ───────────────────────────────────────────────────
HOSPITALS = {
    "US": ["St. Gregory Regional Medical Center", "Riverbend Community Hospital",
           "Lakeview Memorial Hospital", "Northgate University Medical Center"],
    "IN": ["Sri Lakshmi Multispeciality Hospital", "CityCare Hospital & Research Centre",
           "Sunrise Super Speciality Hospital", "Shanti Nursing Home & Polyclinic"],
}
CLINICS = {
    "US": ["Maple Street Family Medicine", "Oakwood Internal Medicine Associates",
           "Cedar Park Primary Care", "Brookside Health Clinic"],
    "IN": ["Dr. {last}'s Clinic", "Arogya Polyclinic", "Sanjeevani Family Clinic",
           "Lifeline Health Care Centre"],
}
LABS_NAMES = {
    "US": ["Meridian Clinical Laboratories", "Summit Diagnostics", "Pinecrest Reference Laboratory"],
    "IN": ["Vijaya Diagnostics Lab", "Metro Path Labs", "Lifespring Diagnostic Centre", "PathCare Laboratories"],
}
IN_QUALS = ["MBBS, MD (General Medicine)", "MBBS, MD (Internal Medicine)", "MBBS, DNB (Family Medicine)",
            "MBBS, MD (Pathology)", "MBBS"]
IN_COUNCILS = ["KMC", "TSMC", "MMC", "DMC", "TNMC", "APMC"]
US_QUALS = ["MD", "DO", "MD, FACP", "NP"]
