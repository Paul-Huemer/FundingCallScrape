"""EU Funding & Tenders Portal (SEDIA search API).

Covers Horizon Europe, Creative Europe, Erasmus+, Digital Europe, CERV, LIFE, … and
cascade-funding (FSTP / open calls by EU projects). Uses the public search API the
portal itself uses; no key beyond the public "SEDIA" key is required.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from ..common import Amount, Call, Http, extract_amounts, html_to_text, iso, today

log = logging.getLogger("scraper.eu")

API = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
TOPIC_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{}"
STATUS_FORTHCOMING, STATUS_OPEN = "31094501", "31094502"

# Dashboard groups: the big programmes get their own group, small ones share "Other programmes".
PROGRAMME_PREFIX = [
    ("HORIZON-MSCA", "EU · Horizon Europe (MSCA)"),
    ("HORIZON", "EU · Horizon Europe"),
    ("CREA", "EU · Creative Europe"),
    ("ERASMUS", "EU · Erasmus+"),
    ("DIGITAL", "EU · Digital Europe"),
    ("CERV", "EU · CERV (Citizens, Equality, Rights)"),
]


def programme_group(identifier: str) -> str:
    for prefix, name in PROGRAMME_PREFIX:
        if identifier.upper().startswith(prefix):
            return name
    return "EU · Other programmes"


def _first(meta: dict, key: str, default=None):
    v = meta.get(key)
    if isinstance(v, list):
        return v[0] if v else default
    return v if v is not None else default


def _date(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("+0000", "+00:00")).date()
    except ValueError:
        return None


def search(http: Http, text: str, page_size: int = 100, max_pages: int = 5) -> list[dict]:
    query = {"bool": {"must": [
        {"terms": {"type": ["1", "2", "8"]}},
        {"terms": {"status": [STATUS_FORTHCOMING, STATUS_OPEN]}},
    ]}}
    files = {
        "query": (None, json.dumps(query), "application/json"),
        "languages": (None, json.dumps(["en"]), "application/json"),
        "sort": (None, json.dumps({"field": "sortStatus", "order": "ASC"}), "application/json"),
    }
    results = []
    for page in range(1, max_pages + 1):
        params = {"apiKey": "SEDIA", "text": text, "pageSize": page_size, "pageNumber": page}
        raw = http.post(API, params=params, files=files)
        d = json.loads(raw)
        batch = d.get("results", [])
        results.extend(batch)
        if len(results) >= d.get("totalResults", 0) or not batch:
            break
    return results


def _amount_from_budget(meta: dict, identifier: str, description: str) -> Amount:
    amt = Amount()
    raw = _first(meta, "budgetOverview")
    if raw:
        try:
            bo = json.loads(raw)
            actions = [a for lst in bo.get("budgetTopicActionMap", {}).values() for a in lst]
            mine = [a for a in actions if a.get("action", "").upper().startswith(identifier.upper())] or (
                actions if len(actions) == 1 else [])
            if mine:
                a = mine[0]
                total = sum(float(v) for v in (a.get("budgetYearMap") or {}).values() if v)
                amt.total_budget_eur = total or None
                mn, mx = a.get("minContribution") or 0, a.get("maxContribution") or 0
                grants = a.get("expectedGrants") or 0
                amt.expected_grants = grants or None
                if mx:
                    amt.min_eur = float(mn) if mn and mn != mx else None
                    amt.max_eur = float(mx)
                    amt.source = "official field"
                elif total and grants:
                    amt.max_eur = round(total / grants, -3)
                    amt.source = "computed"
                    amt.note = f"call budget ÷ {grants} expected grants"
        except (ValueError, TypeError) as e:
            log.debug("budget parse failed for %s: %s", identifier, e)

    text_amt = extract_amounts(description)
    if amt.max_eur is None and text_amt.max_eur:
        amt.min_eur, amt.max_eur, amt.source = text_amt.min_eur, text_amt.max_eur, text_amt.source
    if amt.total_budget_eur is None:
        amt.total_budget_eur = text_amt.total_budget_eur
    amt.funding_rate = amt.funding_rate or text_amt.funding_rate
    amt.note = amt.note or text_amt.note
    return amt


def to_call(r: dict) -> Call | None:
    m = r.get("metadata", {})
    identifier = _first(m, "identifier") or _first(m, "callIdentifier") or r.get("reference", "")
    title = _first(m, "title") or r.get("summary") or identifier
    deadlines = sorted({d for d in (_date(x) for x in (m.get("deadlineDate") or [])) if d})
    upcoming = [d for d in deadlines if d >= today()]
    status_code = _first(m, "status")
    if deadlines and not upcoming:
        return None                                    # all deadlines passed
    is_cascade = str(_first(m, "type")) == "8" or "competitive-calls" in (r.get("url") or "")

    desc_html = " ".join(m.get("descriptionByte") or []) or _first(m, "description", "") or ""
    description = html_to_text(desc_html)
    if not description:
        description = html_to_text(" ".join(m.get("furtherInformation") or [])) or r.get("content", "")

    url = r.get("url") or ""
    if not is_cascade and identifier and ("topicDetails" in url or not url):
        url = TOPIC_URL.format(identifier)

    if is_cascade:
        group = "EU · Cascade funding (open calls by EU projects)"
        amt = extract_amounts(description + " " + html_to_text(" ".join(m.get("beneficiaryAdministration") or [])))
    else:
        group = programme_group(identifier)
        amt = _amount_from_budget(m, identifier, description)

    kws = []
    for k in ("keywords", "tags", "crossCuttingPriorities"):
        for v in m.get(k) or []:
            if v.startswith("["):
                try:
                    kws += json.loads(v)
                    continue
                except ValueError:
                    pass
            if v != identifier and not re.fullmatch(r"[A-Z0-9-]{10,}", v):
                kws.append(v)

    return Call(
        id=f"eu:{identifier or r.get('reference')}",
        title=title.strip(),
        url=url,
        source=group,
        funder="European Commission" if not is_cascade else "EU-funded project (cascade funding)",
        programme=(_first(m, "callIdentifier") or identifier) if not is_cascade else (_first(m, "programme") or ""),
        status="forthcoming" if status_code == STATUS_FORTHCOMING else "open",
        opening_date=iso(_date(_first(m, "startDate"))),
        deadline=iso(upcoming[0]) if upcoming else None,
        deadlines=[iso(d) for d in deadlines],
        deadline_note=_first(m, "deadlineModel"),
        description=description[:12000],
        amount=amt,
        keywords=sorted(set(kws))[:25],
        language="en",
        action_type=(_first(m, "typesOfAction") or "").replace("  ", " "),
    )


def scrape(http: Http, search_terms: list[str]) -> list[Call]:
    seen: dict[str, Call] = {}
    for term in search_terms:
        try:
            res = search(http, term)
        except Exception as e:  # noqa: BLE001
            log.warning("EU search '%s' failed: %s", term, e)
            continue
        n_new = 0
        for r in res:
            c = to_call(r)
            if c and c.id not in seen:
                seen[c.id] = c
                n_new += 1
        log.info("EU portal '%s': %d hits, %d added", term, len(res), n_new)
    return list(seen.values())
