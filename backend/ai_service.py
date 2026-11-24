"""AI service — Gemini-powered document extraction and health chat.

Pipeline for extraction:
    file(s) -> Gemini (vision, JSON schema, temperature 0) -> raw dict
            -> postprocess(): normalise dates/frequencies, recompute abnormal flags,
               score confidence, set needs_review -> dict stored in MedicalDocument.extracted_data

The model call is isolated in `GeminiBackend` so tests/evaluation can swap it out.
"""
import asyncio
import datetime as dt
import mimetypes
import os
import re
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CALL_TIMEOUT = float(os.getenv("LLM_CALL_TIMEOUT", "90"))   # seconds per model call
INFERRED_GENERIC_CONF_CAP = 0.75   # a generic guessed from a brand name is never more certain than this
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
# gemini | groq. Defaults to whichever key is present (Gemini first).
LLM_PROVIDER = os.getenv("LLM_PROVIDER") or ("gemini" if GEMINI_API_KEY else "groq" if GROQ_API_KEY else "gemini")

CATEGORIES = ["prescription", "lab_report", "discharge_summary", "consultation_note",
              "imaging_report", "insurance_or_bill", "other"]
FREQUENCIES = ["once daily", "twice daily", "three times daily", "four times daily",
               "weekly", "as needed", "other"]


# ══════════════════════════════════════════════════════════════════════
#  Extraction schema (sent to Gemini as the response schema)
# ══════════════════════════════════════════════════════════════════════
class MedicationX(BaseModel):
    name: str = Field(description="Medicine name exactly as printed (brand or generic), without Tab./Cap. prefix")
    generic_name: str | None = Field(None, description="Lowercase generic/INN name. If only a brand is printed and you are "
                                                       "not certain of its generic, use null rather than guessing")
    generic_name_source: Literal["printed", "inferred"] | None = Field(
        None, description="'printed' if the generic name literally appears on the document for this medicine; "
                          "'inferred' if you derived it from the brand name using your own knowledge; null if no generic")
    strength: str | None = Field(None, description="e.g. '500 mg'. null for injections dosed in units")
    dosage: str | None = Field(None, description="Amount per dose, e.g. '1 tablet', '14 units'")
    frequency: str | None = Field(None, description=f"One of: {', '.join(FREQUENCIES)}")
    timing: str | None = Field(None, description="e.g. 'after food', 'before food', 'with meals', 'morning', "
                                                 "'bedtime', 'empty stomach'")
    route: str | None = Field(None, description="oral, subcutaneous, topical, ...")
    duration: str | None = Field(None, description="e.g. '5 days', '3 months'; null if not stated")
    instructions: str | None = Field(None, description="Remaining printed directions, verbatim")
    confidence: float = Field(description="0-1 confidence that this row is read correctly")


class LabResultX(BaseModel):
    test_name: str = Field(description="Test name exactly as printed")
    test_value: str = Field(description="Result exactly as printed, without flag marks like (H)")
    unit: str | None = None
    reference_range: str | None = Field(None, description="As printed, e.g. '13.5-17.5', '<200'. null if not printed")
    flag: Literal["H", "L"] | None = Field(None, description="Only if the document prints H/L/High/Low")
    confidence: float


class AllergyX(BaseModel):
    allergen: str
    reaction: str | None = None


class ExtractionX(BaseModel):
    category: Literal["prescription", "lab_report", "discharge_summary", "consultation_note",
                      "imaging_report", "insurance_or_bill", "other"]
    document_date: str | None = Field(None, description="ISO YYYY-MM-DD. Lab report: the REPORTED date")
    doctor: str | None = Field(None, description="Prescriber / attending / ordering physician, with 'Dr.' prefix, "
                                                  "no degrees")
    hospital: str | None = Field(None, description="Clinic, hospital or laboratory name")
    patient_name: str | None = None
    medications: list[MedicationX] = []
    lab_results: list[LabResultX] = []
    diagnoses: list[str] = Field([], description="Conditions diagnosed or treated in THIS document (final/working diagnosis, Dx line). NOT background history")
    past_medical_history: list[str] = Field([], description="Background / chronic conditions listed as past medical history or comorbidities")
    allergies: list[AllergyX] = Field([], description="Real allergens only. NKDA / no known allergies means an EMPTY list")
    follow_up_date: str | None = Field(None, description="ISO date only if an explicit calendar date is printed")
    follow_up_text: str | None = Field(None, description="Relative follow-up as printed, e.g. 'after 2 weeks'")
    admission_date: str | None = None
    discharge_date: str | None = None
    procedures: list[str] = []
    confidence: float = Field(description="Overall 0-1 confidence in the extraction")
    notes: str | None = Field(None, description="Anything illegible, ambiguous or suspicious")


SYSTEM_PROMPT = f"""You extract structured data from medical documents (prescriptions, lab reports, discharge
summaries) from the US and India. They may be clean PDFs, scans or phone photos.

Rules:
1. Extract ONLY what is printed or written. Never invent values. Use null / empty list when absent.
2. Dates -> ISO YYYY-MM-DD. Decide the date convention from context: Indian documents (Rs/₹, +91, UHID, MBBS,
   Reg. No., lakhs/cumm) are DD/MM/YYYY; US documents are MM/DD/YYYY. Month names are unambiguous.
3. Frequency must be one of: {', '.join(FREQUENCIES)}.
   Indian morning-noon-night patterns: 1-0-0 once daily, 1-0-1 twice daily, 1-1-1 three times daily,
   0-0-1 once daily (timing bedtime). BID=twice daily, TID=three times daily, QHS=once daily at bedtime, PRN/SOS=as needed.
4. Prescriptions often print only a brand name (e.g. Pan 40, Dolo 650, Glycomet): keep it in `name` and put the
   lowercase generic in `generic_name` if you are confident. Brand names with a number carry the strength (Dolo 650 = 650 mg).
5. Lab results: copy test_name, value, unit and reference range exactly as printed. `flag` only if H/L is printed.
   Do not judge abnormality yourself. For lab reports the document_date is the report date, not the collection date.
6. follow_up_date only for an explicit calendar date. If it says 'review after 2 weeks', use follow_up_text.
7. `doctor` is the prescribing / attending / ordering physician: 'Dr. First Last' without degrees.
8. List every medication and every lab row; do not summarise or skip.
9. `diagnoses` = what was diagnosed/treated in this document. Conditions under "Past Medical History"/comorbidities
   go in `past_medical_history`, not `diagnoses`.
10. "NKDA", "no known drug allergies", "none" are NOT allergies: return an empty `allergies` list.
11. `strength` is the drug strength (500 mg). `dosage` is the amount taken per dose (1 tablet, 14 units); if the
    document only prints a strength under a "Dose" heading, put it in `strength` and leave `dosage` null.
12. Only fill `duration` when a duration is printed (x 5 days, 3 months). Do not infer it from quantities.
13. Put "at bedtime / at night / 0-0-1" in `timing` as 'bedtime' with frequency 'once daily'.
14. Generic names: set `generic_name_source` to 'printed' only when the generic literally appears on the document
    for that medicine. If you derive it from a brand name, set 'inferred'. Brand-to-generic mappings differ between
    countries and a wrong guess can harm a patient, so when you are not certain of a brand's generic, return
    generic_name = null instead of guessing.
15. Set confidence lower for blurry, cropped or handwritten text, and mention the problem in notes.
"""


# ══════════════════════════════════════════════════════════════════════
#  Backends
# ══════════════════════════════════════════════════════════════════════

class RateLimiter:
    """Spaces calls at least 60/rpm seconds apart (shared by all coroutines using it)."""

    def __init__(self, rpm: float):
        self.gap = 60.0 / rpm if rpm else 0.0
        self._next = 0.0
        self._lock = None

    async def wait(self):
        if not self.gap:
            return
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            now = asyncio.get_event_loop().time()
            delay = max(0.0, self._next - now)
            self._next = max(now, self._next) + self.gap
        if delay:
            await asyncio.sleep(delay)


def retry_delay(err: Exception, attempt: int) -> float:
    """Seconds to wait before retrying. Honours 'retry in 23s' hints on 429s."""
    if isinstance(err, asyncio.TimeoutError):
        return 2.0
    msg = str(err)
    m = re.search(r"retry(?:Delay)?\D{0,12}(\d+(?:\.\d+)?)\s*s", msg, re.I)
    if m:
        return float(m.group(1)) + 1
    if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
        return min(8.0 * (attempt + 1), 30.0)          # transient overload: wait longer each time
    if "429" in msg or "rate" in msg.lower() or "RESOURCE_EXHAUSTED" in msg:
        return 15.0 * (attempt + 1)
    return 2.0 ** attempt


class GeminiBackend:
    """Calls Gemini with the document bytes and returns the parsed JSON dict."""

    def __init__(self, api_key: str | None = None, model: str | None = None, retries: int = 4):
        from google import genai
        key = api_key or GEMINI_API_KEY
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set (see backend/.env.example)")
        self.client = genai.Client(api_key=key)
        self.model = model or GEMINI_MODEL
        self.retries = retries
        self.limiter = RateLimiter(float(os.getenv("GEMINI_RPM", "4")))

    async def extract(self, paths: list[str]) -> dict:
        from google.genai import types
        parts = []
        for p in paths:
            mime = mimetypes.guess_type(p)[0] or "application/octet-stream"
            with open(p, "rb") as f:
                parts.append(types.Part.from_bytes(data=f.read(), mime_type=mime))
        parts.append("Extract the structured data from this document.")
        cfg = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT, temperature=0.0,
            response_mime_type="application/json", response_schema=ExtractionX)
        last = None
        for attempt in range(self.retries):
            try:
                await self.limiter.wait()
                resp = await asyncio.wait_for(
                    self.client.aio.models.generate_content(model=self.model, contents=parts, config=cfg),
                    timeout=CALL_TIMEOUT)
                if resp.parsed is not None:
                    return resp.parsed.model_dump()
                return ExtractionX.model_validate_json(resp.text).model_dump()
            except Exception as e:  # network, quota, malformed JSON
                last = e
                await asyncio.sleep(retry_delay(e, attempt))
        raise RuntimeError(f"Gemini extraction failed after {self.retries} attempts: {last}")

    async def generate(self, system: str, messages: list[dict], max_tokens: int = 2048) -> str:
        """Plain text chat completion. `messages` = [{"role": "user"|"assistant", "content": str}, ...]."""
        from google.genai import types
        contents = [types.Content(role="user" if m["role"] == "user" else "model",
                                  parts=[types.Part.from_text(text=m["content"])]) for m in messages]
        cfg = types.GenerateContentConfig(system_instruction=system, temperature=0.2, max_output_tokens=max_tokens)
        last = None
        for attempt in range(self.retries):
            try:
                await self.limiter.wait()
                resp = await asyncio.wait_for(
                    self.client.aio.models.generate_content(model=self.model, contents=contents, config=cfg),
                    timeout=CALL_TIMEOUT)
                if not (resp.text or "").strip():
                    raise RuntimeError("empty response")
                return resp.text.strip()
            except Exception as e:
                last = e
                await asyncio.sleep(retry_delay(e, attempt))
        raise RuntimeError(f"Gemini generation failed after {self.retries} attempts: {last}")


class GroqBackend:
    """Groq vision model (OpenAI-compatible chat API). PDFs are rendered to page images first.

    Uses JSON mode with the schema embedded in the prompt, then validates against ExtractionX.
    """
    MAX_IMAGES = 5  # Groq's per-request image limit for Llama 4 vision models

    def __init__(self, api_key: str | None = None, model: str | None = None, retries: int = 3):
        from groq import AsyncGroq
        key = api_key or GROQ_API_KEY
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set (see backend/.env.example)")
        self.client = AsyncGroq(api_key=key)
        self.model = model or GROQ_MODEL
        self.retries = retries
        self.limiter = RateLimiter(float(os.getenv("GROQ_RPM", "20")))

    @staticmethod
    def _images(paths: list[str]) -> list[str]:
        """Return base64 JPEG data URLs, one per page, long side capped at 2000px."""
        import base64
        import io
        from PIL import Image
        imgs = []
        for p in paths:
            if p.lower().endswith(".pdf"):
                import pymupdf
                doc = pymupdf.open(p)
                for page in doc:
                    pix = page.get_pixmap(dpi=150)
                    imgs.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
                doc.close()
            else:
                imgs.append(Image.open(p).convert("RGB"))
        urls = []
        for im in imgs[: GroqBackend.MAX_IMAGES]:
            im.thumbnail((2000, 2000))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
            urls.append("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode())
        return urls

    async def extract(self, paths: list[str]) -> dict:
        import json
        schema = json.dumps(ExtractionX.model_json_schema())
        content = [{"type": "text", "text": "Extract the structured data from this document. Respond with ONE JSON "
                                            "object matching this JSON Schema (no prose, no markdown):\n" + schema}]
        content += [{"type": "image_url", "image_url": {"url": u}} for u in self._images(paths)]
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}]
        last = None
        for attempt in range(self.retries):
            try:
                await self.limiter.wait()
                resp = await asyncio.wait_for(self.client.chat.completions.create(
                    model=self.model, messages=messages, temperature=0.0, max_tokens=4096,
                    response_format={"type": "json_object"}), timeout=CALL_TIMEOUT)
                return ExtractionX.model_validate_json(resp.choices[0].message.content).model_dump()
            except Exception as e:  # rate limit, malformed JSON, schema mismatch
                last = e
                await asyncio.sleep(retry_delay(e, attempt))
        raise RuntimeError(f"Groq extraction failed after {self.retries} attempts: {last}")

    async def generate(self, system: str, messages: list[dict], max_tokens: int = 1500) -> str:
        """Plain text chat completion (same contract as GeminiBackend.generate)."""
        payload = [{"role": "system", "content": system}] + [
            {"role": m["role"], "content": m["content"]} for m in messages]
        last = None
        for attempt in range(self.retries):
            try:
                await self.limiter.wait()
                resp = await asyncio.wait_for(self.client.chat.completions.create(
                    model=self.model, messages=payload, temperature=0.2, max_tokens=max_tokens), timeout=CALL_TIMEOUT)
                text = re.sub(r"<think>.*?</think>", "", resp.choices[0].message.content or "", flags=re.S).strip()
                if not text:
                    raise RuntimeError("empty response")
                return text
            except Exception as e:
                last = e
                await asyncio.sleep(retry_delay(e, attempt))
        raise RuntimeError(f"Groq generation failed after {self.retries} attempts: {last}")


class FallbackBackend:
    """Try each backend in order; the first success wins. Gives resilience to one provider/model being
    overloaded (503) or out of quota (429)."""

    def __init__(self, backends: list):
        self.backends = backends
        self.last_used = None

    async def extract(self, paths: list[str]) -> dict:
        errors = []
        for b in self.backends:
            try:
                out = await b.extract(paths)
                self.last_used = f"{type(b).__name__}:{getattr(b, 'model', '')}"
                return out
            except Exception as e:
                errors.append(f"{type(b).__name__}({getattr(b, 'model', '')}): {str(e)[:120]}")
        raise RuntimeError("all providers failed: " + " | ".join(errors))

    async def generate(self, system: str, messages: list[dict], max_tokens: int = 2048) -> str:
        errors = []
        for b in self.backends:
            try:
                out = await b.generate(system, messages, max_tokens)
                self.last_used = f"{type(b).__name__}:{getattr(b, 'model', '')}"
                return out
            except Exception as e:
                errors.append(f"{type(b).__name__}({getattr(b, 'model', '')}): {str(e)[:120]}")
        raise RuntimeError("all providers failed: " + " | ".join(errors))


class CachingBackend:
    """Stores raw model output on disk, keyed by file content + model + prompt. Lets evaluation re-score
    after post-processing changes without spending API quota. Prompt/model changes invalidate the cache."""

    def __init__(self, inner, directory: str):
        import hashlib
        self.inner, self.dir = inner, directory
        os.makedirs(directory, exist_ok=True)
        self._h = hashlib
        self.salt = f"{getattr(inner, 'model', type(inner).__name__)}|{SYSTEM_PROMPT}|{ExtractionX.model_json_schema()}"

    def _path(self, paths: list[str]) -> str:
        h = self._h.sha256(self.salt.encode())
        for p in paths:
            with open(p, "rb") as f:
                h.update(f.read())
        return os.path.join(self.dir, h.hexdigest()[:24] + ".json")

    async def extract(self, paths: list[str]) -> dict:
        import json
        path = self._path(paths)
        if os.path.exists(path):
            return json.load(open(path, encoding="utf-8"))
        out = await self.inner.extract(paths)
        json.dump(out, open(path, "w", encoding="utf-8"))
        return out


def build_default_backend():
    """Provider chain from available keys: preferred provider first, then fallbacks."""
    chain = []
    fallback_models = [m for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash,gemini-3.1-flash-lite").split(",") if m]
    def gemini():
        if GEMINI_API_KEY:
            chain.append(GeminiBackend(retries=3))
            chain.extend(GeminiBackend(model=m, retries=2) for m in fallback_models if m != GEMINI_MODEL)
    def groq():
        if GROQ_API_KEY:
            chain.append(GroqBackend(retries=2))
    for f in ((groq, gemini) if LLM_PROVIDER == "groq" else (gemini, groq)):
        f()
    if not chain:
        raise RuntimeError("No LLM key configured: set GEMINI_API_KEY or GROQ_API_KEY in backend/.env")
    return chain[0] if len(chain) == 1 else FallbackBackend(chain)


_backend = None


def get_backend():
    global _backend
    if _backend is None:
        _backend = build_default_backend()
    return _backend


# ══════════════════════════════════════════════════════════════════════
#  Normalisation + validation
# ══════════════════════════════════════════════════════════════════════
_FREQ_MAP = {
    "once daily": "once daily", "daily": "once daily", "od": "once daily", "qd": "once daily", "1-0-0": "once daily",
    "0-1-0": "once daily", "once a day": "once daily", "every day": "once daily", "qam": "once daily",
    "twice daily": "twice daily", "bid": "twice daily", "bd": "twice daily", "1-0-1": "twice daily",
    "twice a day": "twice daily", "two times daily": "twice daily", "every 12 hours": "twice daily",
    "three times daily": "three times daily", "tid": "three times daily", "tds": "three times daily",
    "1-1-1": "three times daily", "thrice daily": "three times daily", "three times a day": "three times daily",
    "four times daily": "four times daily", "qid": "four times daily", "qds": "four times daily",
    "at bedtime": "at bedtime", "qhs": "at bedtime", "hs": "at bedtime", "0-0-1": "at bedtime",
    "at night": "at bedtime", "bedtime": "at bedtime", "nightly": "at bedtime",  # canonicalised below
    "weekly": "weekly", "once weekly": "weekly", "once a week": "weekly",
    "as needed": "as needed", "prn": "as needed", "sos": "as needed", "if needed": "as needed",
}


def normalize_frequency(v: str | None) -> str | None:
    if not v:
        return None
    k = re.sub(r"\s+", " ", v.strip().lower().rstrip("."))
    if k in _FREQ_MAP:
        return _FREQ_MAP[k]
    for key, val in _FREQ_MAP.items():
        if len(key) > 4 and key in k:
            return val
    return k


_TIMING_MAP = {"after meals": "after food", "after food": "after food", "after a meal": "after food", "p.c.": "after food", "p.c": "after food", "pc": "after food",
               "before meals": "before food", "before food": "before food", "a.c.": "before food", "a.c": "before food", "ac": "before food",
               "with meals": "with meals", "with food": "with meals", "w/ meals": "with meals",
               "morning": "morning", "in the morning": "morning", "qam": "morning",
               "bedtime": "bedtime", "at bedtime": "bedtime", "qhs": "bedtime", "night": "bedtime", "at night": "bedtime",
               "empty stomach": "empty stomach", "on an empty stomach": "empty stomach", "on empty stomach": "empty stomach"}


def normalize_timing(v: str | None) -> str | None:
    if not v:
        return None
    k = re.sub(r"\s+", " ", v.strip().lower().rstrip("."))
    return _TIMING_MAP.get(k, k)


_ROUTE_MAP = {"mouth": "oral", "by mouth": "oral", "orally": "oral", "po": "oral", "p.o.": "oral", "oral": "oral", "per os": "oral",
              "sc": "subcutaneous", "s.c.": "subcutaneous", "sq": "subcutaneous", "subcut": "subcutaneous",
              "subcutaneously": "subcutaneous", "subcutaneous": "subcutaneous",
              "iv": "intravenous", "intravenously": "intravenous", "intravenous": "intravenous",
              "im": "intramuscular", "intramuscularly": "intramuscular", "intramuscular": "intramuscular",
              "topically": "topical", "topical": "topical", "inhaled": "inhalation", "inhalation": "inhalation"}


def normalize_route(v: str | None) -> str | None:
    if not v:
        return None
    k = v.strip().lower().rstrip(".")
    return _ROUTE_MAP.get(k, k)


_GENERIC_SYNONYMS = {"acetaminophen": "paracetamol", "apap": "paracetamol", "adrenaline": "epinephrine",
                     "salbutamol": "albuterol", "frusemide": "furosemide", "glyburide": "glibenclamide"}
_SALTS = ("hydrochloride", "hcl", "sodium", "potassium", "besylate", "maleate", "tartrate", "succinate", "mesylate",
          "calcium", "hydrobromide", "phosphate")


def normalize_generic(v: str | None) -> str | None:
    """Canonical generic name: lowercase, salt suffixes dropped, INN/USAN synonyms unified,
    'a and b' / 'a/b' -> 'a-b'."""
    if not v:
        return None
    k = re.sub(r"\s+", " ", v.strip().lower())
    k = re.sub(r"\s*(?:/|\band\b|\+|&)\s*", "-", k)
    parts = []
    for part in k.split("-"):
        words = [w for w in part.split() if w not in _SALTS]
        part = " ".join(words)
        parts.append(_GENERIC_SYNONYMS.get(part, part))
    return "-".join(p for p in parts if p)


_NAME_NOISE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|ug|g|ml|iu|units?|%)\b|\b(?:tab|tabs|tablet|tablets|cap|caps|capsule|capsules|"
    r"inj|injection|syrup|susp|suspension|cream|drops?|er|sr|xr|cr)\b\.?", re.I)


def drug_core_name(name: str | None) -> str:
    """Printed medicine name with strength/form words removed: 'Tab. Metformin 850 mg' -> 'metformin'."""
    return re.sub(r"\s+", " ", _NAME_NOISE.sub(" ", name or "")).strip(" .,-").lower()


def generic_is_printed_in_name(generic: str | None, name: str | None) -> bool:
    """True when the generic name is just the printed name itself (ignoring strength / dosage form)."""
    g, core = normalize_generic(generic), normalize_generic(drug_core_name(name))
    return bool(g) and bool(core) and g == core


def normalize_dosage(v: str | None) -> str | None:
    if not v:
        return None
    k = re.sub(r"\s+", " ", v.strip().lower())
    k = re.sub(r"\btabs?\b\.?", "tablet", k)
    k = re.sub(r"\bcaps?\b\.?", "capsule", k)
    k = re.sub(r"\b(tablet|capsule)s\b", r"\1", k)
    return k


def canon_freq_timing(freq: str | None, timing: str | None) -> tuple[str | None, str | None]:
    """'at bedtime' is a timing, not a frequency: (at bedtime, None) -> (once daily, bedtime)."""
    f, t = normalize_frequency(freq), normalize_timing(timing)
    if f == "at bedtime":
        f, t = "once daily", t or "bedtime"
    return f, t


_NO_ALLERGY = re.compile(r"^\s*(nkda|nka|nkfa|none|nil|n/?a|no known|no allerg|not known|denies)", re.I)


_DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y", "%B %d, %Y", "%b %d, %Y"]


def normalize_date(v: str | None, prefer_dmy: bool = False) -> str | None:
    """Return ISO date or None when unparseable. Slash dates follow `prefer_dmy`."""
    if not v:
        return None
    s = v.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        try:
            return dt.date.fromisoformat(s).isoformat()
        except ValueError:
            return None
    fmts = list(_DATE_FORMATS)
    if not prefer_dmy:
        fmts = ["%m/%d/%Y", "%m-%d-%Y"] + fmts
    for f in fmts:
        try:
            return dt.datetime.strptime(s, f).date().isoformat()
        except ValueError:
            continue
    return None


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", ""))
    return float(m.group()) if m else None


def parse_range(ref: str | None) -> tuple[float | None, float | None] | None:
    if not ref:
        return None
    r = ref.strip().replace("–", "-").replace("to", "-")
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*", r)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.fullmatch(r"\s*[<≤]=?\s*(\d+(?:\.\d+)?)\s*", r)
    if m:
        return None, float(m.group(1))
    m = re.fullmatch(r"\s*[>≥]=?\s*(\d+(?:\.\d+)?)\s*", r)
    if m:
        return float(m.group(1)), None
    return None


def abnormal_from_range(value: str, ref: str | None) -> tuple[bool | None, str | None]:
    """(is_abnormal, flag) computed from the numeric value and printed reference range."""
    v, rng = _num(value), parse_range(ref)
    if v is None or rng is None:
        return None, None
    lo, hi = rng
    if lo is not None and v < lo:
        return True, "L"
    if hi is not None and v > hi:
        return True, "H"
    return False, None


def _looks_indian(raw: dict) -> bool:
    blob = " ".join(str(raw.get(k) or "") for k in ("doctor", "hospital", "notes"))
    units = " ".join(str(l.get("unit") or "") for l in raw.get("lab_results", []))
    pat = " ".join(str(m.get("instructions") or "") for m in raw.get("medications", []))
    return bool(re.search(r"MBBS|Reg\.? ?No|lakhs?|cumm|UHID|\+91|\b[01]-[01]-[01]\b|SOS", f"{blob} {units} {pat}", re.I))


def postprocess(raw: dict) -> dict:
    """Normalise model output and attach validation/confidence. Pure function (no I/O)."""
    out = dict(raw)
    dmy = _looks_indian(raw)
    issues: list[str] = []
    today = dt.date.today()

    for k in ("document_date", "follow_up_date", "admission_date", "discharge_date"):
        if raw.get(k):
            iso = normalize_date(raw[k], dmy)
            if iso is None:
                issues.append(f"unparseable {k}: {raw[k]}")
            out[k] = iso
    if out.get("document_date") and dt.date.fromisoformat(out["document_date"]) > today + dt.timedelta(days=1):
        issues.append("document_date is in the future")

    meds = []
    for m in raw.get("medications", []):
        m = dict(m)
        m["frequency"], m["timing"] = canon_freq_timing(m.get("frequency"), m.get("timing"))
        m["route"] = normalize_route(m.get("route"))
        if m.get("generic_name"):
            m["generic_name"] = normalize_generic(m["generic_name"])
        m["dosage"] = normalize_dosage(m.get("dosage")) or m.get("dosage")
        if m.get("duration") and m["duration"].strip().lower() in ("as needed", "prn", "sos", "n/a", "-", "—"):
            m["duration"] = None
        if m.get("generic_name"):
            m["generic_name"] = m["generic_name"].strip().lower()
        if not m.get("name"):
            continue
        # provenance of the generic name: a guess from a brand must be visible to the user
        if m.get("generic_name"):
            same = generic_is_printed_in_name(m["generic_name"], m["name"])
            src = "printed" if same else m.get("generic_name_source")
            if src not in ("printed", "inferred"):
                src = "inferred"            # unknown provenance and different from the printed name
        else:
            src = None
        m["generic_name_source"] = src
        m["generic_inferred"] = src == "inferred"
        if m["generic_inferred"]:
            m["confidence"] = min(float(m.get("confidence", 1)), INFERRED_GENERIC_CONF_CAP)
        meds.append(m)
    out["medications"] = meds
    out["inferred_generics"] = [f"{m['name']} -> {m['generic_name']}" for m in meds if m["generic_inferred"]]
    out["allergies"] = [a for a in raw.get("allergies", []) if a.get("allergen") and not _NO_ALLERGY.match(a["allergen"])]

    labs = []
    for l in raw.get("lab_results", []):
        l = dict(l)
        ab, flag = abnormal_from_range(l.get("test_value", ""), l.get("reference_range"))
        l["is_abnormal"] = ab if ab is not None else (True if l.get("flag") else None)
        l["flag"] = flag or l.get("flag")
        if ab is not None and raw_flag_conflict(l, raw):
            issues.append(f"printed flag disagrees with value/range for {l.get('test_name')}")
        labs.append(l)
    out["lab_results"] = labs

    # ── confidence ──
    conf = float(raw.get("confidence") or 0.0)
    row_confs = [float(x.get("confidence", 1)) for x in meds + labs]
    if row_confs:
        conf = min(conf, sum(row_confs) / len(row_confs) + 0.1)
    cat = raw.get("category", "other")
    if cat == "other" or not (meds or labs or raw.get("diagnoses")):
        conf *= 0.5
        issues.append("no clinical content found")
    if not out.get("document_date"):
        conf *= 0.85
        issues.append("document date missing")
    if cat == "lab_report" and not labs:
        conf *= 0.5
        issues.append("lab report without lab rows")
    if cat in ("prescription", "discharge_summary") and not meds:
        conf *= 0.7
        issues.append("no medications found")
    low = [m["name"] for m in meds if float(m.get("confidence", 1)) < 0.6] + \
          [l["test_name"] for l in labs if float(l.get("confidence", 1)) < 0.6]
    if low:
        issues.append("low-confidence rows: " + ", ".join(low[:5]))

    out["confidence"] = round(max(0.0, min(1.0, conf)), 3)
    out["validation_issues"] = issues
    out["needs_review"] = out["confidence"] < 0.75 or bool(issues)
    out["raw_text"] = raw.get("raw_text", "")
    return out


def raw_flag_conflict(lab: dict, raw: dict) -> bool:
    """True when the model printed an H/L flag that contradicts the numeric comparison."""
    for r in raw.get("lab_results", []):
        if r.get("test_name") == lab.get("test_name"):
            return r.get("flag") is not None and r.get("flag") != lab.get("flag")
    return False


# ══════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════
def _empty(reason: str) -> dict:
    return {"category": "other", "document_date": None, "doctor": None, "hospital": None, "medications": [],
            "lab_results": [], "diagnoses": [], "allergies": [], "follow_up_date": None, "raw_text": "",
            "confidence": 0.0, "needs_review": True, "validation_issues": [reason]}


async def extract_from_document(file_path: str, file_type: str | None = None, extra_paths: list[str] | None = None,
                                backend=None) -> dict:
    """Extract structured medical data from an uploaded document (PDF or image).

    Never raises: on failure returns an empty result flagged needs_review with the reason,
    so an upload is never lost because the AI step failed.
    """
    try:
        b = backend or get_backend()
        raw = await b.extract([file_path] + (extra_paths or []))
        return postprocess(raw)
    except Exception as e:
        return _empty(f"extraction failed: {e}")
