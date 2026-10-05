"""Watchlist: funders without a call database (foundations, public funds, industry grants …).

Each entry in config/watchlist.json names the page where the funder announces calls. On every run
the page is fetched and scanned:

* a future date near a deadline keyword  -> status "open" with that deadline
* a "closed / no call" phrase, or no date -> status "watch" (shown as a monitored funder with its
  usual call rhythm), or "rolling" for funders that accept applications any time
* amounts: the curated per-project figures from the entry (funder guidelines), else whatever the
  page text states

So the list doubles as a register of niche funders, and a call shows up with a deadline as soon
as the funder publishes one.
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from bs4 import BeautifulSoup

from ..common import ROOT, Amount, Call, Http, extract_amounts, find_dates, iso, squash, today

log = logging.getLogger("scraper.watchlist")

DEADLINE_KW = re.compile(
    r"Einreich\w*|Deadline|Frist|Stichtag|Bewerbungs\w*|Antrags\w*|Abgabe\w*|Call\s+(?:closes|deadline)|"
    r"submission|apply\s+by|applications?\s+(?:due|close|open)|closes?|until|bis\s+(?:zum|spätestens)?|"
    r"läuft\s+bis|endet|spätestens",
    re.I,
)
CLOSED_DEFAULT = re.compile(
    r"derzeit\s+(?:keine|nicht)|aktuell\s+(?:keine|nicht)|keine\s+(?:laufende|offene|aktuelle)n?\s+(?:Ausschreibung|Calls?)|"
    r"Ausschreibung\s+(?:ist\s+)?(?:geschlossen|beendet|abgeschlossen)|Einreichung\s+(?:ist\s+)?(?:geschlossen|nicht\s+möglich)|"
    r"no\s+(?:open|current)\s+calls?|(?:call|applications?)\s+(?:is|are)\s+(?:now\s+)?closed|currently\s+closed|"
    r"nächste\s+(?:Ausschreibung|Call)\s+(?:folgt|wird)|noch\s+nicht\s+fixiert",
    re.I,
)


def _page_text(http: Http, url: str, selector: str | None) -> str:
    raw = http.get(url, timeout=20)
    if raw.lstrip().startswith(("{", "[")):
        return squash(raw)
    soup = BeautifulSoup(raw, "html.parser")
    for t in soup(["script", "style", "svg", "noscript", "nav", "footer"]):
        t.decompose()
    node = None
    for sel in ([selector] if selector else []) + ["main", "article", "#content", ".content", "body"]:
        node = soup.select_one(sel)
        if node and len(node.get_text(strip=True)) > 200:
            break
    return squash((node or soup).get_text(" "))


def _deadlines(text: str, patterns: list[str]) -> list:
    found = []
    for p in patterns:                          # entry-specific patterns win
        for m in re.finditer(p, text, re.I):
            found += find_dates(m.group(1) if m.groups() else m.group(0))
    if not found:                               # generic: dates within ~90 chars after a deadline keyword
        for m in DEADLINE_KW.finditer(text):
            found += find_dates(text[m.start(): m.end() + 90])
    return sorted({d for d in found if d >= today()})


def _next_recurring(mmdd: list[str]) -> list:
    out = []
    for x in mmdd:
        m, d = map(int, x.split("-"))
        for y in (today().year, today().year + 1):
            dt = date(y, m, d)
            if dt >= today():
                out.append(dt)
                break
    return out


def _entry_to_call(http: Http, e: dict) -> Call:
    url = e["url"]
    check = e.get("check_url") or url
    text, error = "", None
    try:
        text = _page_text(http, check, e.get("selector"))
    except Exception as ex:  # noqa: BLE001 - still list the funder, flag the fetch problem
        error = str(ex)[:120]
        log.warning("watchlist %s: %s", e["id"], error)

    closed = any(re.search(p, text, re.I) for p in e.get("closed_patterns", [])) or bool(CLOSED_DEFAULT.search(text))
    if e.get("ignore_default_closed"):
        closed = any(re.search(p, text, re.I) for p in e.get("closed_patterns", []))
    dls = [] if e.get("never_parse_dates") else _deadlines(text, e.get("deadline_patterns", []))
    horizon = e.get("max_deadline_days", 550)
    dls = [d for d in dls if (d - today()).days <= horizon]

    # fixed yearly dates (e.g. board deadlines 1 Feb / 1 Apr / 1 Sep), given as "MM-DD"
    recurring = sorted(_next_recurring(e.get("recurring_deadlines", [])))
    if recurring and not dls:
        dls = recurring

    if dls and not (closed and not e.get("deadline_patterns")):
        status, deadline = "open", dls[0]
    elif e.get("rolling"):
        status, deadline = "rolling", None
    else:
        status, deadline = "watch", None

    a = e.get("amount") or {}
    amt = Amount(min_eur=a.get("min_eur"), max_eur=a.get("max_eur"), funding_rate=a.get("funding_rate"),
                 note=a.get("note"), currency=a.get("currency", "EUR"), source="funder guidelines" if (a.get("max_eur") or a.get("min_eur")) else "not stated")
    if amt.max_eur is None and text and not e.get("no_text_amount"):
        ext = extract_amounts(text[:15000])
        if ext.max_eur:
            amt.min_eur, amt.max_eur, amt.source = ext.min_eur, ext.max_eur, ext.source
            amt.funding_rate = amt.funding_rate or ext.funding_rate

    note = e.get("rhythm")
    if error:
        note = f"{note + ' · ' if note else ''}page could not be checked on last run"
    elif status == "watch":
        note = f"No open call found on the funder's page{' · usual rhythm: ' + note if note else ''}"

    return Call(
        id=f"watch:{e['id']}",
        title=e["name"],
        url=url,
        source=e["group"],
        funder=e["funder"],
        programme=e.get("programme", ""),
        status=status,
        deadline=iso(deadline),
        deadlines=[iso(d) for d in dls[:4]],
        deadline_note=note,
        description=squash(f"{e.get('description', '')} {text[:6000]}"),
        summary="",
        amount=amt,
        eligibility=e.get("eligibility", ""),
        keywords=e.get("tags", []),
        language=e.get("language", "de"),
        fit_reason=e.get("fit_reason", ""),
    )


def curated_fit(path=None) -> dict[str, str]:
    path = path or ROOT / "config" / "watchlist.json"
    if not path.exists():
        return {}
    return {f"watch:{e['id']}": e.get("fit", "") for e in json.loads(path.read_text(encoding="utf-8"))["funders"]}


def scrape(http: Http, path=None) -> list[Call]:
    path = path or ROOT / "config" / "watchlist.json"
    if not path.exists():
        return []
    entries = [e for e in json.loads(path.read_text(encoding="utf-8"))["funders"] if not e.get("disabled")]
    log.info("Watchlist: checking %d funder pages ...", len(entries))

    def one(e: dict) -> Call | None:
        try:
            c = _entry_to_call(http, e)
        except Exception as ex:  # noqa: BLE001
            log.warning("watchlist entry %s failed: %s", e.get("id"), ex)
            return None
        c.summary = e.get("summary", "")           # curated summary; the summarizer fills it if empty
        if c.summary:
            c.language = "en"                      # curated summaries are written in English
        if e.get("partner_only"):
            c.eligibility = "⚠ Partner role only – " + c.eligibility
        return c

    # independent sites -> check in parallel so one slow page doesn't hold up the update
    with ThreadPoolExecutor(max_workers=8) as pool:
        calls = [c for c in pool.map(one, entries) if c]
    n_open = sum(c.status == "open" for c in calls)
    log.info("Watchlist: %d funders checked, %d with an announced deadline", len(calls), n_open)
    return calls
