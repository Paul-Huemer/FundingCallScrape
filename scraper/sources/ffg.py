"""FFG – Österreichische Forschungsförderungsgesellschaft.

The public listing page (/foerderungen) is served stale by the CDN, so we use the
Drupal views AJAX endpoint that backs the "Weitere Angebote" block: it pages through
every open (Geöffnet) and planned (geplant) call. Detail pages carry a "Steckbrief"
with Einreichzeitraum, Max. Förderung and eligible applicant types.
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..common import Call, Http, extract_amounts, find_dates, iso, parse_number, squash, today

log = logging.getLogger("scraper.ffg")

BASE = "https://www.ffg.at"
AJAX = BASE + "/views/ajax"
AJAX_PARAMS = {
    "_wrapper_format": "drupal_ajax",
    "view_name": "foederung_services_and_events",
    "view_display_id": "block_1",
    "view_args": "203308",
    "view_path": "/node/203308",
    "type[0]": "call",
}


def _ajax_html(raw: str) -> str:
    try:
        cmds = json.loads(raw)
    except ValueError:
        return ""
    return "".join(c.get("data", "") for c in cmds if isinstance(c.get("data"), str))


def list_calls(http: Http, max_pages: int = 40) -> list[dict]:
    items, seen = [], set()
    for page in range(max_pages):
        raw = http.get(AJAX, params={**AJAX_PARAMS, "page": page},
                       headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
        soup = BeautifulSoup(_ajax_html(raw), "html.parser")
        cards = soup.select('article[data-component-id="ao_canvas:call-teaser"]')
        new = 0
        for card in cards:
            a = card.find("a", href=True)
            if not a:
                continue
            href = urljoin(BASE, a["href"])
            if href in seen:
                continue
            seen.add(href)
            new += 1
            lines = [l for l in card.get_text("\n", strip=True).split("\n") if l.strip()]
            items.append({
                "url": href,
                "title": (card.find("h2").get_text(" ", strip=True) if card.find("h2") else lines[0]),
                "subtitle": card.find("h3").get_text(" ", strip=True) if card.find("h3") else "",
                "teaser": " ".join(p.get_text(" ", strip=True) for p in card.select("div p")),
                "lines": lines,
            })
        if not cards or not new:
            break
    log.info("FFG: %d calls in listing", len(items))
    return items


def _after(lines: list[str], label: str) -> str | None:
    for i, l in enumerate(lines):
        if l.lower().startswith(label.lower()) and i + 1 < len(lines):
            return lines[i + 1]
    return None


def _section(text_lines: list[str], start_pat: str, stop_pats: tuple[str, ...]) -> str:
    out, on = [], False
    for l in text_lines:
        if re.match(start_pat, l, re.I):
            on = True
            continue
        if on and any(re.match(p, l, re.I) for p in stop_pats):
            break
        if on:
            out.append(l)
    return " ".join(out)


def parse_detail(http: Http, item: dict) -> Call | None:
    html = http.get(item["url"])
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "svg", "nav", "footer"]):
        t.decompose()
    lines = [l.strip() for l in soup.get_text("\n", strip=True).split("\n") if l.strip()]

    # Only the part up to the "Weitere Angebote" block belongs to this call
    if "Weitere Angebote" in lines:
        lines = lines[: lines.index("Weitere Angebote")]
    try:
        start = max(i for i, l in enumerate(lines) if l == item["title"])
    except ValueError:
        start = 0
    body = lines[start:]

    steck = body[body.index("Steckbrief"):] if "Steckbrief" in body else item["lines"]
    status_raw = (steck[1] if len(steck) > 1 else "").lower()
    period = _after(steck, "Einreichzeitraum") or _after(item["lines"], "Einreichzeitraum") or ""
    max_f = _after(steck, "Max. Förderung") or _after(item["lines"], "Max. Förderung") or ""
    elig = []
    if "Förderung für" in steck:
        i = steck.index("Förderung für") + 1
        while i < len(steck) and steck[i] not in ("Kooperation", "Geltungsbereich", "Förderbare Kosten", "Geldgeber", "Kontakt"):
            elig.append(steck[i]); i += 1
    coop = _after(steck, "Kooperation") or ""
    scope = _after(steck, "Geltungsbereich") or ""

    dates = find_dates(period)
    opening = dates[0] if dates else None
    deadline = dates[-1] if len(dates) >= 2 else (dates[0] if dates else None)
    status = "forthcoming" if "geplant" in status_raw else "open"
    rolling = bool(re.search(r"laufend|jederzeit|kontinuierlich", period + " " + " ".join(body[:40]), re.I))
    if deadline and deadline < today():
        return None
    if "geschlossen" in status_raw:
        return None

    stop = (r"^Steckbrief$", r"^Wer wird gefördert", r"^Wie hoch", r"^Was sind die Einreich", r"^Wie erfolgt",
            r"^Wann gibt es", r"^Kontakt$", r"^Ausschreibungsdokumente$")
    what = _section(body, r"^(Was wird gefördert|Worum geht es|Ziel|Ziele|Inhalt|Gegenstand)", stop)
    who = _section(body, r"^Wer wird gefördert", stop)
    how_much = _section(body, r"^Wie hoch", stop)
    intro = " ".join(body[1:8])
    meta_desc = soup.find("meta", attrs={"name": "description"})
    meta_desc = meta_desc["content"] if meta_desc and meta_desc.get("content") else ""

    description = squash(" ".join(x for x in [meta_desc, item.get("subtitle", ""), item.get("teaser", ""), what or intro] if x))
    full_text = squash(" ".join(body))

    amt = extract_amounts(" ".join([how_much, meta_desc, full_text[:6000]]))
    v = parse_number(re.sub(r"[^\d.,]", "", max_f), None) if re.search(r"\d", max_f) else None
    if v:
        amt.max_eur, amt.source = v, "official field"
        if amt.min_eur and amt.min_eur >= v:
            amt.min_eur = None
    if amt.total_budget_eur and amt.max_eur and amt.total_budget_eur < amt.max_eur:
        amt.total_budget_eur = None      # a "total" below the official cap is a sub-budget, not the call budget
    rate = re.search(r"Förder(?:ungs)?quote[^%]{0,40}?(\d{2,3})\s?%", how_much + " " + full_text, re.I)
    if rate:
        amt.funding_rate = f"max. {rate[1]}%"

    funder = "FFG"
    geldgeber = _after(steck, "Geldgeber")
    if geldgeber and geldgeber not in ("Kontakt",) and len(geldgeber) < 40:
        funder = f"FFG (on behalf of {geldgeber})"

    eligibility = ", ".join(elig)
    if coop:
        eligibility += f" · Kooperation: {coop}"
    if scope:
        eligibility += f" · {scope}"
    if who:
        eligibility = (eligibility + " · " if eligibility else "") + who[:300]

    slug = item["url"].rstrip("/").rsplit("/", 1)[-1]
    return Call(
        id=f"ffg:{slug}",
        title=item["title"],
        url=item["url"],
        source="FFG · Austrian Research Promotion Agency",
        funder=funder,
        programme=item.get("subtitle", ""),
        status="rolling" if rolling and status == "open" else status,
        opening_date=iso(opening),
        deadline=iso(deadline),
        deadlines=[iso(d) for d in dates[1:]] if len(dates) > 1 else [iso(d) for d in dates],
        deadline_note=period or None,
        description=description[:8000] + " " + full_text[:4000],
        amount=amt,
        eligibility=eligibility,
        language="de",
    )


# FFG publishes national info pages for EU calls; the EU portal source has these at
# topic level with official budgets, so they are skipped here to avoid duplicates.
EU_MIRROR = re.compile(r"^(Horizon Europe|LIFE Call|Digital Europe Programme|Binnenmarktprogramm|"
                       r"Innovative Health Initiative|Chips JU)", re.I)


def scrape(http: Http) -> list[Call]:
    calls = []
    for item in list_calls(http):
        if EU_MIRROR.search(item["title"]):
            continue
        try:
            c = parse_detail(http, item)
            if c:
                calls.append(c)
        except Exception as e:  # noqa: BLE001
            log.warning("FFG detail failed %s: %s", item["url"], e)
    log.info("FFG: %d open/planned calls parsed", len(calls))
    return calls
