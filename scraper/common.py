"""Shared helpers: data model, cached HTTP, text cleanup, date and money parsing."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache" / "http"
log = logging.getLogger("scraper")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 DML-Antragsscraper/1.0"
)


# --------------------------------------------------------------------------- model

@dataclass
class Amount:
    """Funding amount for ONE project (what a single consortium/applicant can get)."""
    min_eur: float | None = None
    max_eur: float | None = None
    total_budget_eur: float | None = None   # whole call budget, for context
    funding_rate: str | None = None         # e.g. "70%" or "100% (lump sum)"
    expected_grants: int | None = None
    source: str = "not stated"              # "official field" | "computed" | "extracted from text" | "AI extracted" | "not stated"
    note: str | None = None                 # short free text (e.g. "lump sum", "per partner")
    currency: str = "EUR"                   # the *_eur fields hold this currency's amount (e.g. USD grants)


@dataclass
class Call:
    id: str
    title: str
    url: str
    source: str                 # group key shown in dashboard, e.g. "EU · Horizon Europe"
    funder: str                 # e.g. "European Commission", "FFG"
    programme: str = ""         # sub-programme / call identifier
    status: str = "open"        # open | forthcoming | rolling
    opening_date: str | None = None   # ISO date
    deadline: str | None = None       # ISO date (next submission deadline)
    deadlines: list[str] = field(default_factory=list)   # all stage deadlines
    deadline_note: str | None = None  # e.g. "two-stage", "continuous until 31.12."
    description: str = ""       # cleaned plain text used for scoring/summarising
    summary: str = ""
    fit_reason: str = ""
    amount: Amount = field(default_factory=Amount)
    eligibility: str = ""
    keywords: list[str] = field(default_factory=list)
    language: str = "en"
    relevance: int = 0
    matched_areas: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)   # lab research-area keys, strongest first
    action_type: str = ""
    first_seen: str | None = None     # ISO date the scraper first found this call (for "newest")
    is_new: bool = False              # first found in the latest run

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- http

class Http:
    """requests.Session with polite retry and a small on-disk cache (default TTL 12h)."""

    def __init__(self, ttl_hours: float = 12, delay: float = 0.3):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "de-AT,de;q=0.9,en;q=0.8"})
        self.ttl = ttl_hours * 3600
        self.delay = delay
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _key(self, method: str, url: str, extra: str) -> Path:
        h = hashlib.sha1(f"{method} {url} {extra}".encode()).hexdigest()
        return CACHE_DIR / h

    def get(self, url: str, *, params: dict | None = None, headers: dict | None = None,
            use_cache: bool = True, timeout: int = 40) -> str:
        key = self._key("GET", url, json.dumps(params, sort_keys=True))
        return self._request("GET", url, key, use_cache, params=params, headers=headers, timeout=timeout)

    def post(self, url: str, *, params: dict | None = None, files=None, data=None,
             use_cache: bool = True, timeout: int = 60) -> str:
        extra = json.dumps([params, str(files), str(data)], sort_keys=True, default=str)
        key = self._key("POST", url, extra)
        return self._request("POST", url, key, use_cache, params=params, files=files, data=data, timeout=timeout)

    def _request(self, method, url, key: Path, use_cache: bool, **kw) -> str:
        if use_cache and key.exists() and time.time() - key.stat().st_mtime < self.ttl:
            return key.read_text(encoding="utf-8")
        last_err = None
        for attempt in range(3):
            try:
                r = self.s.request(method, url, **kw)
                if r.status_code in (429, 502, 503, 504):
                    raise requests.HTTPError(f"{r.status_code}")
                r.raise_for_status()
                r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else "utf-8"
                text = r.text
                key.write_text(text, encoding="utf-8")
                time.sleep(self.delay)
                return text
            except Exception as e:  # noqa: BLE001 - network errors of all kinds are retried
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"{method} {url} failed: {last_err}")


# --------------------------------------------------------------------------- text

def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "svg"]):
        t.decompose()
    for br in soup.find_all(["br", "p", "li", "div", "h1", "h2", "h3", "h4", "tr"]):
        br.insert_after("\n")
    text = soup.get_text(" ")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


_BOILER = re.compile(
    r"(cookie|eCall|login|newsletter|kontakt|contact|e-mail|telefon|\+43|download|"
    r"Ausschreibungsdokumente|Leitfaden|Mehr erfahren|Mehr Information|please refer|"
    r"see the (?:call|work programme) document|General conditions|Admissibility)",
    re.I,
)


def extractive_summary(text: str, max_chars: int = 420) -> str:
    """Fallback summary: first informative sentences of the description."""
    text = squash(re.sub(r"(Expected Outcomes?|Expected Impacts?|Scope|Objectives?|Ziel(e)?|Was wird gefördert\??|Worum geht es\??)\s*:\s*", "", text or ""))
    # protect abbreviations so "10 Mio. EUR" or "z. B. Schulen" don't end a sentence
    dot = "․"  # placeholder for a protected full stop
    text = re.sub(r"\b([zZuUdDeEiI])\.\s?([BAhge])\.", lambda m: f"{m[1]}{dot} {m[2]}{dot}", text)
    abbr = r"\b(Mio|Mrd|Tsd|max|min|ca|bzw|inkl|exkl|vgl|Nr|Abs|Art|lit|approx|incl|etc|Dr|Prof|Mag|DI|St)\.(?=\s)"
    text = re.sub(abbr, lambda m: m[1] + dot, text)
    sentences = [x.replace(dot, ".") for x in re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9„\"(])", text)]
    out = []
    for s in sentences:
        s = s.strip(" -•·")
        if len(s) < 40 or _BOILER.search(s):
            continue
        if sum(len(x) for x in out) + len(s) > max_chars and out:
            break
        out.append(s)
        if len(out) >= 3:
            break
    summary = " ".join(out)
    if len(summary) > max_chars:
        summary = summary[: max_chars - 1].rsplit(" ", 1)[0] + "…"
    return summary


# --------------------------------------------------------------------------- dates

_MONTHS = {
    "jan": 1, "jän": 1, "jänner": 1, "januar": 1, "january": 1,
    "feb": 2, "februar": 2, "february": 2,
    "mär": 3, "märz": 3, "mar": 3, "march": 3, "maerz": 3,
    "apr": 4, "april": 4,
    "mai": 5, "may": 5,
    "jun": 6, "juni": 6, "june": 6,
    "jul": 7, "juli": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "okt": 10, "oct": 10, "oktober": 10, "october": 10,
    "nov": 11, "november": 11,
    "dez": 12, "dec": 12, "dezember": 12, "december": 12,
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

DATE_PATTERNS = [
    (re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(20\d\d)\b"), lambda m: (int(m[3]), int(m[2]), int(m[1]))),
    (re.compile(rf"\b(\d{{1,2}})\.?\s+({_MONTH_RE})\.?\s+(20\d\d)\b", re.I),
     lambda m: (int(m[3]), _MONTHS[m[2].lower()], int(m[1]))),
    (re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}}),?\s+(20\d\d)\b", re.I),
     lambda m: (int(m[3]), _MONTHS[m[1].lower()], int(m[2]))),
]


def find_dates(text: str) -> list[date]:
    found = []
    for rx, fn in DATE_PATTERNS:
        for m in rx.finditer(text or ""):
            try:
                y, mo, d = fn(m)
                found.append((m.start(), date(y, mo, d)))
            except (ValueError, KeyError):
                pass
    return [d for _, d in sorted(found)]


def iso(d: date | datetime | None) -> str | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat()


def today() -> date:
    return date.today()


# --------------------------------------------------------------------------- money

_NUM = r"\d{1,3}(?:[.,  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_UNIT = r"Mio\.?|Millionen|Million(?:en)?|millions?|mn|Mrd\.?|Milliarden|billion|bn|k|Tsd\.?|thousand|Tausend"
_CUR = r"EUR|€|Euro|euros?"

_MONEY_RE = re.compile(
    rf"(?:(?:{_CUR})\s*(?P<n1>{_NUM})\s*(?P<u1>{_UNIT})?)"
    rf"|(?:(?P<n2>{_NUM})\s*(?P<u2>{_UNIT})?\s*(?:{_CUR}))",
    re.I,
)
_RANGE_RE = re.compile(
    rf"(?:between|zwischen|from|von)\s+(?:(?:{_CUR})\s*)?(?P<a>{_NUM})\s*(?P<ua>{_UNIT})?\s*(?:(?:{_CUR})\s*)?"
    rf"(?:and|und|to|bis)\s+(?:(?:{_CUR})\s*)?(?P<b>{_NUM})\s*(?P<ub>{_UNIT})?\s*(?:{_CUR})?",
    re.I,
)

PER_PROJECT_CTX = re.compile(
    r"pro\s+Projekt|je\s+Projekt|per\s+(?:project|proposal|grant|applicant|beneficiary|team|participant)|"
    r"Förder(?:ungs)?summe|Förderhöhe|max(?:imal|imum)?\.?\s|bis\s+zu|up\s+to|"
    r"EU\s+contribution|contribution\s+of|grant\s+(?:amount|size|of)|lump\s+sum|"
    r"Förderung\s+(?:von|beträgt)|maximale\s+Förderung|Zuschuss",
    re.I,
)
TOTAL_CTX = re.compile(
    r"insgesamt|Gesamtbudget|Budget|zur\s+Verfügung|Ausschreibungsvolumen|Fördervolumen|"
    r"total|overall|available|indicative\s+budget|call\s+budget|Dotierung",
    re.I,
)


def parse_number(num: str, unit: str | None) -> float | None:
    s = num.replace(" ", " ").replace(" ", " ").strip()
    unit = (unit or "").lower().rstrip(".")
    if re.fullmatch(r"\d{1,3}(?:[.,  ]\d{3})+", s) and not unit:
        s = re.sub(r"[.,  ]", "", s)               # 1.500.000 / 1,500,000 / 60 000
    elif re.fullmatch(r"\d{1,3}(?:[. ]\d{3})+,\d+", s):
        s = re.sub(r"[. ]", "", s).replace(",", ".")  # 1.500.000,00
    elif re.fullmatch(r"\d{1,3}(?:[, ]\d{3})+\.\d+", s):
        s = re.sub(r"[, ]", "", s)                    # 1,500,000.00
    else:
        s = s.replace(" ", "").replace(",", ".")
        if s.count(".") > 1:
            s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    if unit.startswith(("mio", "million", "mn")):
        v *= 1e6
    elif unit.startswith(("mrd", "milliard", "billion", "bn")):
        v *= 1e9
    elif unit in ("k", "tsd", "thousand", "tausend"):
        v *= 1e3
    return v


def extract_amounts(text: str) -> Amount:
    """Heuristically find per-project min/max and total call budget in free text."""
    text = squash(text)
    amt = Amount()
    per_project: list[float] = []
    totals: list[float] = []

    for m in _RANGE_RE.finditer(text):
        ub = m["ub"] or m["ua"]
        a = parse_number(m["a"], m["ua"] or ub)
        b = parse_number(m["b"], ub)
        ctx = text[max(0, m.start() - 160): m.end() + 80]
        if a and b and 1_000 <= a <= b and re.search(_CUR, ctx, re.I):
            if TOTAL_CTX.search(text[max(0, m.start() - 60): m.start()]) and not PER_PROJECT_CTX.search(ctx):
                continue
            amt.min_eur, amt.max_eur = a, b
            amt.source = "extracted from text"
            break

    for m in _MONEY_RE.finditer(text):
        v = parse_number(m["n1"] or m["n2"], m["u1"] or m["u2"])
        if not v or v < 1_000 or v > 2e9:      # >2 bn = programme-wide envelopes, not call budgets
            continue
        kind = _classify(text, m.start(), m.end())
        if kind == "project":
            per_project.append(v)
        elif kind == "total":
            totals.append(v)

    if amt.max_eur is None and per_project:
        amt.max_eur = max(per_project) if len(set(per_project)) == 1 else _pick_cap(per_project, totals)
        amt.source = "extracted from text"
    if totals:
        amt.total_budget_eur = max(totals)
    if amt.max_eur and amt.total_budget_eur and amt.max_eur > amt.total_budget_eur:
        amt.max_eur, amt.total_budget_eur = amt.total_budget_eur, amt.max_eur

    rate = re.search(r"(?:Förder(?:ungs)?quote|funding rate|Förderintensität|Förderhöhe)[^%]{0,60}?(\d{2,3})\s?%", text, re.I)
    if rate:
        amt.funding_rate = f"{rate[1]}%"
    if re.search(r"lump[\s-]sum|Pauschal", text, re.I):
        amt.note = "lump sum"
    return amt


def _classify(text: str, start: int, end: int) -> str | None:
    """Decide whether the money mention at [start:end] is a per-project cap or a call total,
    using whichever context keyword sits closest (same sentence preferred)."""
    sent_start = max(0, text.rfind(". ", 0, start), text.rfind("; ", 0, start), start - 120)
    sent_end_candidates = [i for i in (text.find(". ", end), text.find("; ", end)) if i != -1]
    sent_end = min(sent_end_candidates + [end + 60])
    before, after = text[sent_start:start], text[end:sent_end]
    best: tuple[int, str] | None = None
    for rx, kind in ((PER_PROJECT_CTX, "project"), (TOTAL_CTX, "total")):
        for mm in rx.finditer(before):
            d = len(before) - mm.end()
            best = min(best, (d, kind)) if best else (d, kind)
        mm = rx.search(after)
        if mm:
            d = mm.start() + 5   # slight preference for keywords before the number
            best = min(best, (d, kind)) if best else (d, kind)
    return best[1] if best else None


def _pick_cap(per_project: list[float], totals: list[float]) -> float:
    # the largest per-project figure that is not also a call total
    cands = [v for v in per_project if v not in totals] or per_project
    return max(cands)


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
