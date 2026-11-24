#!/usr/bin/env python
"""Score AI extraction against the synthetic answer keys.

    python evaluate.py --backend oracle            # scorer sanity check (should be ~100%)
    python evaluate.py --backend noisy             # simulated errors (scorer should catch them)
    python evaluate.py --backend gemini --limit 20 # real model (needs GEMINI_API_KEY)
    python evaluate.py --backend groq --limit 20   # Groq vision (needs GROQ_API_KEY)

Options: --truth DIR (default ../tools/synth/output), --category, --region, --degradation,
         --concurrency N, --out report.json, --show-failures
"""
import argparse
import asyncio
import copy
import json
import os
import random
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher

from ai_service import (extract_from_document, normalize_frequency, canon_freq_timing, normalize_route, normalize_generic, normalize_dosage, GeminiBackend, GroqBackend,
                        FallbackBackend, CachingBackend, build_default_backend)

# ══════════════════════════════════════════════════════════════════════
#  Matching helpers
# ══════════════════════════════════════════════════════════════════════
norm = lambda s: re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def fuzzy(a, b, thr=0.85) -> bool:
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    return a == b or a in b or b in a or SequenceMatcher(None, a, b).ratio() >= thr


def name_match(truth, pred) -> bool:
    """People/places: truth tokens (minus 'dr') must all appear in prediction."""
    t = set(norm(truth).split()) - {"dr"}
    p = set(norm(pred).split()) - {"dr"}
    return bool(t) and (t <= p or fuzzy(truth, pred, 0.9))


def num_equal(a, b) -> bool:
    try:
        return abs(float(str(a).replace(",", "")) - float(str(b).replace(",", ""))) < 1e-9
    except ValueError:
        return norm(a) == norm(b)


def range_equal(a, b) -> bool:
    f = lambda s: re.sub(r"\s+", "", str(s or "")).replace("–", "-").replace("to", "-")
    return f(a) == f(b)


def unit_equal(a, b) -> bool:
    f = lambda s: re.sub(r"[\s]+", "", str(s or "").lower()).replace("µ", "u")
    return f(a) == f(b)


def prf(tp, n_truth, n_pred):
    p = tp / n_pred if n_pred else (1.0 if n_truth == 0 else 0.0)
    r = tp / n_truth if n_truth else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


# ══════════════════════════════════════════════════════════════════════
#  Per-document scoring → flat dict of metric -> (correct, total)
# ══════════════════════════════════════════════════════════════════════
def score_doc(truth: dict, pred: dict) -> dict:
    m = defaultdict(lambda: [0, 0])

    def add(key, ok, applicable=True):
        if applicable:
            m[key][1] += 1
            m[key][0] += int(bool(ok))

    add("category", truth["category"] == pred.get("category"))
    add("document_date", truth["document_date"] == pred.get("document_date"))
    add("doctor", name_match(truth["doctor"], pred.get("doctor")))
    add("hospital", name_match(truth["hospital"], pred.get("hospital")))
    add("patient_name", name_match(truth["patient_name"], pred.get("patient_name")))

    # follow-up: exact date, and hallucination when truth has none
    add("follow_up_date", truth.get("follow_up_date") == pred.get("follow_up_date"))
    add("follow_up_no_hallucination", pred.get("follow_up_date") is None, truth.get("follow_up_date") is None)

    # diagnoses
    tp = 0
    used = set()
    for td in truth["diagnoses"]:
        for i, pd_ in enumerate(pred.get("diagnoses", [])):
            if i not in used and fuzzy(td, pd_, 0.8):
                used.add(i); tp += 1; break
    m["diagnosis_tp"][0] += tp
    m["diagnosis_truth"][0] += len(truth["diagnoses"])
    m["diagnosis_pred"][0] += len(pred.get("diagnoses", []))

    # past medical history (only documents whose truth lists it)
    if "past_medical_history" in truth:
        tp = sum(any(fuzzy(t_, p_, 0.8) for p_ in pred.get("past_medical_history", [])) for t_ in truth["past_medical_history"])
        m["pmh_tp"][0] += tp
        m["pmh_truth"][0] += len(truth["past_medical_history"])
        m["pmh_pred"][0] += len(pred.get("past_medical_history", []))

    # medications — match on generic name first, then brand name
    pm = pred.get("medications", [])
    used = set()
    tp = 0
    for tm in truth["medications"]:
        hit = None
        for i, p in enumerate(pm):
            if i in used:
                continue
            if tm["generic_name"] and fuzzy(tm["generic_name"], p.get("generic_name") or "", 0.9) \
                    or fuzzy(tm["name"], p.get("name"), 0.9) \
                    or fuzzy(tm["generic_name"], p.get("name"), 0.9):
                hit = i
                break
        if hit is None:
            continue
        used.add(hit); tp += 1
        p = pm[hit]
        add("med_generic_name", normalize_generic(tm["generic_name"]) == normalize_generic(p.get("generic_name") or p.get("name")))
        # --- generic-name safety: guesses must be visible, wrong guesses must be flagged ---
        pg, tg = normalize_generic(p.get("generic_name")), normalize_generic(tm["generic_name"])
        brand_only = not tm.get("generic_printed", True)
        if pg:
            add("generic_source", p.get("generic_name_source") == ("inferred" if brand_only else "printed"))
            if pg != tg:
                add("wrong_generic_flagged", bool(p.get("generic_inferred")))      # the dangerous case if False
            if p.get("generic_inferred"):
                add("inferred_generic_correct", pg == tg)
        if brand_only:
            add("generic_abstained", not pg)                                        # honest "don't know"
        add("med_strength", norm(tm["strength"]) == norm(p.get("strength")), tm["strength"] is not None)
        add("med_dosage", normalize_dosage(tm["dosage"]) == normalize_dosage(p.get("dosage")), tm["dosage"] is not None and tm.get("dosage_printed", True))
        tf, tt = canon_freq_timing(tm["frequency"], tm["timing"])
        pf, pt = canon_freq_timing(p.get("frequency"), p.get("timing"))
        add("med_frequency", tf == pf)
        add("med_timing", (tt == pt) or fuzzy(tt, pt) if tt else not pt)
        add("med_duration", norm(tm["duration"]) == norm(p.get("duration")), tm.get("duration_printed", True))
        add("med_route", normalize_route(tm["route"]) == (normalize_route(p.get("route")) or "oral"), tm.get("route_printed", True))
    m["med_tp"][0] += tp
    m["med_truth"][0] += len(truth["medications"])
    m["med_pred"][0] += len(pm)

    # labs — match by test name
    pl = pred.get("lab_results", [])
    used = set()
    tp = 0
    for tl in truth["lab_results"]:
        hit = next((i for i, p in enumerate(pl) if i not in used and fuzzy(tl["test_name"], p.get("test_name"), 0.9)), None)
        if hit is None:
            continue
        used.add(hit); tp += 1
        p = pl[hit]
        add("lab_value", num_equal(tl["test_value"], p.get("test_value")))
        add("lab_unit", unit_equal(tl["unit"], p.get("unit")))
        add("lab_range", range_equal(tl["reference_range"], p.get("reference_range")), tl["reference_range"] is not None)
        add("lab_abnormal", bool(tl["is_abnormal"]) == bool(p.get("is_abnormal")), tl["is_abnormal"] is not None)
    m["lab_tp"][0] += tp
    m["lab_truth"][0] += len(truth["lab_results"])
    m["lab_pred"][0] += len(pl)

    # allergies
    ta, pa = truth.get("allergies", []), pred.get("allergies", [])
    tp = sum(any(fuzzy(t["allergen"], p.get("allergen"), 0.85) for p in pa) for t in ta)
    m["allergy_tp"][0] += tp
    m["allergy_truth"][0] += len(ta)
    m["allergy_pred"][0] += len(pa)
    return {k: tuple(v) for k, v in m.items()}


def merge(docs: list[dict]) -> dict:
    tot = defaultdict(lambda: [0, 0])
    for d in docs:
        for k, (a, b) in d.items():
            tot[k][0] += a
            tot[k][1] += b
    return tot


GENERIC_SAFETY = ["generic_source", "inferred_generic_correct", "wrong_generic_flagged", "generic_abstained"]
ACC_METRICS = ["category", "document_date", "doctor", "hospital", "patient_name", "follow_up_date",
               "follow_up_no_hallucination", "med_generic_name", "med_strength", "med_dosage", "med_frequency",
               "med_timing", "med_duration", "med_route", "lab_value", "lab_unit", "lab_range", "lab_abnormal"] + GENERIC_SAFETY
SETS = [("past history", "pmh"), ("diagnoses", "diagnosis"), ("medications (found)", "med"), ("lab rows (found)", "lab"),
        ("allergies", "allergy")]


def summarize(tot) -> dict:
    out = {k: (tot[k][0] / tot[k][1] if tot[k][1] else None) for k in ACC_METRICS}
    for label, p in SETS:
        _, r, f = prf(tot[f"{p}_tp"][0], tot[f"{p}_truth"][0], tot[f"{p}_pred"][0])
        pr, _, _ = prf(tot[f"{p}_tp"][0], tot[f"{p}_truth"][0], tot[f"{p}_pred"][0])
        out[f"{label}: precision"], out[f"{label}: recall"], out[f"{label}: F1"] = pr, r, f
    return out



def diff_doc(t: dict, p: dict) -> list[str]:
    """Human-readable list of mismatches between truth `t` and prediction `p`."""
    out = []
    for k in ("category", "document_date", "follow_up_date"):
        if t.get(k) != p.get(k):
            out.append(f"{k}: expected {t.get(k)!r}, got {p.get(k)!r}")
    for k in ("doctor", "hospital", "patient_name"):
        if not name_match(t[k], p.get(k)):
            out.append(f"{k}: expected {t[k]!r}, got {p.get(k)!r}")
    pm, used = p.get("medications", []), set()
    for tm in t["medications"]:
        hit = next((i for i, x in enumerate(pm) if i not in used and (
            fuzzy(tm["generic_name"], x.get("generic_name") or "", 0.9) or fuzzy(tm["name"], x.get("name"), 0.9)
            or fuzzy(tm["generic_name"], x.get("name"), 0.9))), None)
        if hit is None:
            out.append(f"med MISSING: {tm['name']} ({tm['generic_name']})")
            continue
        used.add(hit)
        x = pm[hit]
        tf, tt = canon_freq_timing(tm["frequency"], tm["timing"])
        pf, pt = canon_freq_timing(x.get("frequency"), x.get("timing"))
        checks = [("strength", norm(tm["strength"]) == norm(x.get("strength")), tm["strength"], x.get("strength")),
                  ("frequency", tf == pf, tf, pf),
                  ("timing", (tt == pt) or fuzzy(tt, pt) if tt else not pt, tt, pt),
                  ("generic_name", normalize_generic(tm["generic_name"]) == normalize_generic(x.get("generic_name") or x.get("name")),
                   tm["generic_name"], (f"{x.get('generic_name')} [{x.get('generic_name_source')}"
                                        f"{', FLAGGED' if x.get('generic_inferred') else ', NOT FLAGGED'}]"
                                        if x.get("generic_name") else "None [abstained: no generic shown]")),
                  ]
        if tm.get("route_printed", True):
            checks.append(("route", normalize_route(tm["route"]) == (normalize_route(x.get("route")) or "oral"),
                           tm["route"], x.get("route")))
        if tm.get("dosage_printed", True) and tm["dosage"] is not None:
            checks.append(("dosage", normalize_dosage(tm["dosage"]) == normalize_dosage(x.get("dosage")), tm["dosage"], x.get("dosage")))
        if tm.get("duration_printed", True):
            checks.append(("duration", norm(tm["duration"]) == norm(x.get("duration")), tm["duration"], x.get("duration")))
        for f, same, exp, got in checks:
            if not same:
                out.append(f"med {tm['name']}.{f}: expected {exp!r}, got {got!r}")
    for i, x in enumerate(pm):
        if i not in used:
            out.append(f"med EXTRA: {x.get('name')}")
    pl, used = p.get("lab_results", []), set()
    for tl in t["lab_results"]:
        hit = next((i for i, x in enumerate(pl) if i not in used and fuzzy(tl["test_name"], x.get("test_name"), 0.9)), None)
        if hit is None:
            out.append(f"lab MISSING: {tl['test_name']} {tl['test_value']}")
            continue
        used.add(hit)
        if not num_equal(tl["test_value"], pl[hit].get("test_value")):
            out.append(f"lab {tl['test_name']}: expected {tl['test_value']}, got {pl[hit].get('test_value')}")
    for i, x in enumerate(pl):
        if i not in used:
            out.append(f"lab EXTRA: {x.get('test_name')}")
    for td in t["diagnoses"]:
        if not any(fuzzy(td, x, 0.8) for x in p.get("diagnoses", [])):
            out.append(f"diagnosis MISSING: {td!r} (got {p.get('diagnoses')})")
    for x in p.get("diagnoses", []):
        if not any(fuzzy(td, x, 0.8) for td in t["diagnoses"]):
            out.append(f"diagnosis EXTRA: {x!r}")
    for t_ in t.get("past_medical_history", []):
        if not any(fuzzy(t_, x, 0.8) for x in p.get("past_medical_history", [])):
            out.append(f"history MISSING: {t_!r}")
    for ta in t.get("allergies", []):
        if not any(fuzzy(ta["allergen"], x.get("allergen"), 0.85) for x in p.get("allergies", [])):
            out.append(f"allergy MISSING: {ta['allergen']}")
    for x in p.get("allergies", []):
        if not any(fuzzy(ta["allergen"], x.get("allergen"), 0.85) for ta in t.get("allergies", [])):
            out.append(f"allergy EXTRA: {x.get('allergen')}")
    return out

# ══════════════════════════════════════════════════════════════════════
#  Offline backends
# ══════════════════════════════════════════════════════════════════════
class OracleBackend:
    """Returns the truth as 'model output' (with printed-style flags). Tests scorer + postprocess."""

    def __init__(self, truth_by_file):
        self.t = truth_by_file

    async def extract(self, paths):
        e = copy.deepcopy(self.t[os.path.basename(paths[0])])
        e["confidence"] = 0.95
        for m in e["medications"]:
            m["confidence"] = 0.95
        for l in e["lab_results"]:
            l["confidence"] = 0.95
        return e


class NoisyBackend(OracleBackend):
    """Injects realistic mistakes so we can confirm the scorer notices them."""

    def __init__(self, truth_by_file, seed=0):
        super().__init__(truth_by_file)
        self.rng = random.Random(seed)

    async def extract(self, paths):
        e = await super().extract(paths)
        r = self.rng
        if r.random() < 0.15:
            e["document_date"] = None
        if r.random() < 0.10 and e.get("document_date"):          # day/month swap
            y, mo, d = e["document_date"].split("-")
            e["document_date"] = f"{y}-{d}-{mo}" if int(d) <= 12 else e["document_date"]
        if e.get("follow_up_date") is None and r.random() < 0.3:   # hallucination
            e["follow_up_date"] = "2026-12-01"
        e["medications"] = [m for m in e["medications"] if r.random() > 0.1]
        for m in e["medications"]:
            if r.random() < 0.1:
                m["strength"] = "10 mg"
            if r.random() < 0.1:
                m["frequency"] = "BID"                              # non-normalised, postprocess should fix
        for l in e["lab_results"]:
            if r.random() < 0.05:
                l["test_value"] = str(float(l["test_value"]) * 10)  # decimal slip
        return e


# ══════════════════════════════════════════════════════════════════════
#  Runner / report
# ══════════════════════════════════════════════════════════════════════
def load_truth(root, a):
    rows = []
    for fn in sorted(os.listdir(os.path.join(root, "truth"))):
        t = json.load(open(os.path.join(root, "truth", fn), encoding="utf-8"))
        if a.category and t["category"] != a.category:
            continue
        if a.region and t["region"] != a.region:
            continue
        if a.degradation and t["degradation"] != a.degradation:
            continue
        rows.append(t)
    if a.limit and a.limit < len(rows):          # evenly spaced sample so every type/region is represented
        step = len(rows) / a.limit
        rows = [rows[int(i * step)] for i in range(a.limit)]
    return rows


async def run(a):
    root = os.path.abspath(a.truth)
    rows = load_truth(root, a)
    if not rows:
        sys.exit("no documents match the filters")
    by_file = {f: r["expected"] for r in rows for f in r["files"]}
    backend = {"oracle": lambda: OracleBackend(by_file), "noisy": lambda: NoisyBackend(by_file, a.seed),
               "gemini": lambda: GeminiBackend(model=a.model), "groq": lambda: GroqBackend(model=a.model),
               "auto": lambda: build_default_backend()}[a.backend]()
    if a.cache and a.backend in ("gemini", "groq", "auto"):
        backend = CachingBackend(backend, a.cache)
    if a.cache_only:
        if not isinstance(backend, CachingBackend):
            sys.exit("--cache-only needs --cache DIR and a real backend")
        have = [r for r in rows if os.path.exists(backend._path([os.path.join(root, "documents", f) for f in r["files"]]))]
        print(f"cache-only: {len(have)} of {len(rows)} sampled documents have cached model output")
        rows = have
        if not rows:
            sys.exit("nothing cached for these documents")
    sem = asyncio.Semaphore(a.concurrency)

    async def one(r):
        paths = [os.path.join(root, "documents", f) for f in r["files"]]
        async with sem:
            pred = await extract_from_document(paths[0], extra_paths=paths[1:], backend=backend)
        return r, pred

    results = await asyncio.gather(*[one(r) for r in rows])
    per_doc = []
    for r, pred in results:
        per_doc.append(dict(id=r["id"], region=r["region"], category=r["category"], degradation=r["degradation"],
                            scores=score_doc(r["expected"], pred), confidence=pred.get("confidence"),
                            needs_review=pred.get("needs_review"), issues=pred.get("validation_issues", []),
                            diff=diff_doc(r["expected"], pred)))
    return per_doc


def fmt(v):
    return "   n/a" if v is None else f"{v * 100:5.1f}%"


def print_report(per_doc, show_failures, show_diff=False):
    overall = summarize(merge([d["scores"] for d in per_doc]))
    print(f"\n{len(per_doc)} documents\n")
    print("OVERALL")
    for k, v in overall.items():
        print(f"  {k:36s}{fmt(v)}")

    for dim in ("category", "region", "degradation"):
        groups = defaultdict(list)
        for d in per_doc:
            groups[d[dim]].append(d["scores"])
        print(f"\nBY {dim.upper()}  (date | doctor | med name F1 | med freq | lab value | lab abnormal)")
        for g, docs in sorted(groups.items()):
            s = summarize(merge(docs))
            print(f"  {g:20s} n={len(docs):3d}  {fmt(s['document_date'])} {fmt(s['doctor'])} "
                  f"{fmt(s['medications (found): F1'])} {fmt(s['med_frequency'])} {fmt(s['lab_value'])} "
                  f"{fmt(s['lab_abnormal'])}")

    flagged = sum(bool(d["needs_review"]) for d in per_doc)
    print(f"\nflagged needs_review: {flagged}/{len(per_doc)}")
    if show_failures:
        print("\nDOCUMENTS WITH ERRORS")
        for d in per_doc:
            wrong = [k for k, (a, b) in d["scores"].items() if k in ACC_METRICS and b and a < b]
            miss = d["scores"]["med_truth"][0] - d["scores"]["med_tp"][0] + \
                   d["scores"]["lab_truth"][0] - d["scores"]["lab_tp"][0]
            if wrong or miss:
                print(f"  {d['id']:28s} {d['degradation']:5s} conf={d['confidence']}  wrong={wrong} missing_rows={miss}")
    if show_diff:
        print("\nMISMATCH DETAIL")
        for d in per_doc:
            if d["diff"] or d["issues"]:
                print(f"  {d['id']}  [{d['degradation']}, conf={d['confidence']}]")
                for line in d["diff"]:
                    print(f"      {line}")
                if d["issues"] and d["confidence"] == 0:
                    print(f"      ISSUE: {d['issues'][0][:200]}")
    return overall


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--truth", default=os.path.join(os.path.dirname(__file__), "..", "tools", "synth", "output"))
    ap.add_argument("--backend", choices=["gemini", "groq", "auto", "oracle", "noisy"], default="oracle")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--category")
    ap.add_argument("--region", choices=["US", "IN"])
    ap.add_argument("--degradation", choices=["clean", "scan", "photo"])
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--model", help="override model id (gemini or groq backend)")
    ap.add_argument("--cache", help="directory to cache raw model output (free re-scoring)")
    ap.add_argument("--cache-only", action="store_true", help="score only documents already cached; make no API calls")
    ap.add_argument("--diff", action="store_true", help="print expected vs predicted for every mismatch")
    ap.add_argument("--out")
    ap.add_argument("--show-failures", action="store_true")
    a = ap.parse_args()
    per_doc = asyncio.run(run(a))
    overall = print_report(per_doc, a.show_failures, a.diff)
    if a.out:
        json.dump(dict(backend=a.backend, overall=overall, documents=[
            {**d, "scores": {k: list(v) for k, v in d["scores"].items()}} for d in per_doc]),
            open(a.out, "w", encoding="utf-8"), indent=2)
        print(f"\nreport written to {a.out}")


if __name__ == "__main__":
    main()
