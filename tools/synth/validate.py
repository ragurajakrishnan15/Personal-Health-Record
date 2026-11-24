"""Sanity-check generated output: files exist, truth is internally consistent,
and printed text in clean PDFs contains the expected values."""
import json, os, sys, collections
import pymupdf

out = sys.argv[1] if len(sys.argv) > 1 else "output"
errs, stats = [], collections.Counter()
for fn in sorted(os.listdir(f"{out}/truth")):
    t = json.load(open(f"{out}/truth/{fn}", encoding="utf-8"))
    e = t["expected"]
    stats[(t["region"], t["category"])] += 1
    for f in t["files"]:
        if not os.path.exists(f"{out}/documents/{f}"):
            errs.append(f"{t['id']}: missing {f}")
    for lab in e["lab_results"]:
        if lab["reference_range"] and lab["flag"] is None and lab["is_abnormal"]:
            errs.append(f"{t['id']}: abnormal without flag {lab['test_name']}")
    if t["category"] == "lab_report" and not e["lab_results"]:
        errs.append(f"{t['id']}: lab report with no labs")
    if t["category"] != "lab_report" and not e["medications"]:
        errs.append(f"{t['id']}: no medications")
    # text check on clean PDFs
    if t["degradation"] == "clean":
        text = " ".join(p.get_text() for p in pymupdf.open(f"{out}/documents/{t['files'][0]}"))
        flat = " ".join(text.split())
        for lab in e["lab_results"]:
            if lab["test_name"] not in flat or lab["test_value"] not in flat:
                errs.append(f"{t['id']}: lab not found in PDF text: {lab['test_name']} {lab['test_value']}")
        for m in e["medications"]:
            if m["name"] not in flat:
                errs.append(f"{t['id']}: med not found in PDF text: {m['name']}")
        if e["patient_name"] not in flat:
            errs.append(f"{t['id']}: patient name missing")
print("documents by (region, category):")
for k, v in sorted(stats.items()):
    print(f"  {k}: {v}")
abn = sum(l["is_abnormal"] is True for f in os.listdir(f"{out}/truth")
          for l in json.load(open(f"{out}/truth/{f}", encoding="utf-8"))["expected"]["lab_results"])
print(f"abnormal lab values in truth: {abn}")
print("\nERRORS:" if errs else "\nOK: no problems found")
for e in errs[:30]:
    print(" ", e)
sys.exit(1 if errs else 0)
