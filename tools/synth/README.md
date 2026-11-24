# Synthetic medical document generator

Generates fictional prescriptions, lab reports and discharge summaries in **US** and **Indian**
formats, plus an answer key (JSON) for each, for developing and scoring the AI extraction in
`backend/ai_service.py`.

```bash
pip install faker reportlab pymupdf pillow numpy
python generate.py --count 60 --seed 42 --out output --clean
python validate.py output
```

Options: `--region US|IN|both`, `--mix 0.4,0.3,0.3` (clean PDF / scan / phone photo),
`--no-watermark`, `--count N`, `--seed N` (deterministic).

## What varies
| | US | India |
|---|---|---|
| Dates | MM/DD/YYYY, "Jan 16, 2026" | DD/MM/YYYY, "15-Jul-2026" |
| Rx | generic names, "Sig: 1 tab PO BID", NPI/DEA, Disp/Refills | brand names (Atorva, Pan 40, Dolo 650), "1-0-1", "after food", Reg. No., optional handwriting font |
| Labs | WBC 10^3/uL, Platelets 10^3/uL, BUN, ALT | TLC cells/cumm, Platelets lakhs/cumm, Blood Urea, SGPT |
| Discharge | MRN, Attending, ICD-10 codes | UHID, IP No., Consultant |

Also randomised: fonts, colours, layout, abbreviated vs verbose sigs, relative follow-ups
("review after 2 weeks", truth `follow_up_date = null`), patient allergies, abnormal flags,
scan/photo degradation (rotation, blur, noise, perspective, shadow, JPEG).

## Output
- `documents/` PDFs and JPGs
- `truth/<id>.json` expected extraction (`expected`) + generation metadata
- `manifest.jsonl`, `patients.json` (coherent patient histories, reusable as seed data)

## Ground-truth notes for scoring
- `generic_name` is the **normalised** target; Indian Rx often print only the brand (`generic_printed: false`).
- Discharge-summary labs are printed without ranges: `reference_range`/`is_abnormal` are `null`.
- Lab `document_date` is the **reported** date; `generation.collection_date` is the sample date.
- All content is fictional; a small footer says so (disable with `--no-watermark`).
