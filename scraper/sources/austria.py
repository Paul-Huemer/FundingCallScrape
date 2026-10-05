"""Other Austrian, regional and cross-border funders.

FWF (JSON search API), OeAD Sparkling Science 2.0, netidee, Interreg Bayern–Österreich,
Interreg Österreich–Tschechien and aws Proof of Concept. Each parser is small and
independent; a failing site only drops its own calls.

Not scraped on purpose: WWTF and Wirtschaftsagentur Wien (Vienna-based applicants only),
Interreg Central Europe (no call until the post-2027 programme), Land OÖ research calls
(run through FFG eCall, so they already appear in the FFG source).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..common import Amount, Call, Http, extract_amounts, find_dates, iso, parse_number, squash, today

log = logging.getLogger("scraper.austria")


def _text(html: str, selector: str | None = None) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "svg", "nav", "footer", "header"]):
        t.decompose()
    node = soup.select_one(selector) if selector else None
    return squash((node or soup).get_text(" "))


def _money(s: str) -> float | None:
    m = re.search(r"(\d[\d.,  ]*)\s*(Mio\.?|Millionen)?\s*(?:€|EUR|Euro)", s, re.I)
    return parse_number(m[1].strip(), m[2]) if m else None


# --------------------------------------------------------------------------- FWF

def fwf(http: Http) -> list[Call]:
    """FWF programme portfolio via the Solr JSON endpoint behind /foerdern/foerderportfolio."""
    url = "https://www.fwf.ac.at/search.json"   # the /en/ index has no programme documents
    params = {
        "tx_solr[q]": "*",
        "tx_solr[filter][0]": "type:programs",
        "tx_solr[filter][1]": "programHasOpenSubmissions:Offene Einreichungen",
        "tx_solr[page]": 1, "tx_solr[perPage]": 200,
    }
    d = json.loads(http.get(url, params=params, headers={"Accept": "application/json"}))
    docs = d.get("documents") or d.get("response", {}).get("docs") or _find_docs(d)
    calls = []
    for doc in docs:
        title = doc.get("title") or ""
        link = doc.get("url") or ""
        if link.startswith("/"):
            link = "https://www.fwf.ac.at" + link
        status_s = doc.get("programSubmissionStatus_stringS") or ""
        end_ts = doc.get("programEndTimestamp_intS")
        start_ts = doc.get("programStartTimestamp_intS")
        rolling = bool(re.search(r"laufend|ongoing|continuous", status_s, re.I))
        end = datetime.fromtimestamp(int(end_ts)).date() if end_ts and not rolling else None
        if end and end < today():
            continue
        vol = doc.get("programVolume_stringS") or ""
        amt = Amount()
        v = _money(vol) if vol else None
        if v:
            amt.max_eur, amt.source = v, "official field"
        desc = squash(" ".join(str(doc.get(k, "")) for k in ("programKeywords_textS", "teaser", "content") if doc.get(k)))
        try:  # detail page gives the programme description and "Maximal … €" when the volume field is empty
            page = _text(http.get(link), "main")
            desc = squash(desc + " " + page[:5000])
            if not amt.max_eur:
                ext = extract_amounts(page)
                amt.max_eur, amt.min_eur, amt.source = ext.max_eur, ext.min_eur, ext.source
        except Exception as e:  # noqa: BLE001
            log.debug("FWF detail %s: %s", link, e)
        calls.append(Call(
            id=f"fwf:{link.rstrip('/').rsplit('/', 1)[-1]}",
            title=title, url=link,
            source="FWF · Austrian Science Fund", funder="FWF",
            programme=", ".join(doc.get("category") or []) if isinstance(doc.get("category"), list) else "",
            status="rolling" if rolling else "open",
            opening_date=iso(datetime.fromtimestamp(int(start_ts)).date()) if start_ts and not rolling else None,
            deadline=iso(end), deadlines=[iso(end)] if end else [],
            deadline_note=status_s or None,
            description=desc[:8000], amount=amt,
            eligibility="Researchers at Austrian research institutions (incl. universities of applied sciences)",
            language="en",
        ))
    log.info("FWF: %d open programmes", len(calls))
    return calls


def _find_docs(d) -> list[dict]:
    """The Solr wrapper nests results differently between versions; find the list of dicts with 'title'."""
    if isinstance(d, list) and d and isinstance(d[0], dict) and "title" in d[0]:
        return d
    if isinstance(d, dict):
        for v in d.values():
            r = _find_docs(v)
            if r:
                return r
    if isinstance(d, list):
        for v in d:
            r = _find_docs(v)
            if r:
                return r
    return []


# --------------------------------------------------------------------------- Sparkling Science

def sparkling_science(http: Http) -> list[Call]:
    base = "https://oead.at/de/studieren-forschen-lehren/citizen-science/sparkling-science"
    url = base + "/ausschreibungen"
    text = _text(http.get(url), "main")
    m_end = re.search(r"bis\s+(\d{1,2}\.\s*\w+\s+20\d\d)(?:,\s*(\d{1,2}:\d{2})\s*Uhr)?", text)
    m_start = re.search(r"startete\s+mit\s+(\d{1,2}\.\s*\w+\s+20\d\d)", text)
    if not m_end:
        log.info("Sparkling Science: no open call found")
        return []
    end = find_dates(m_end[1])
    end = end[0] if end else None
    if not end or end < today():
        return []
    start = find_dates(m_start[1])[0] if m_start and find_dates(m_start[1]) else None
    m_title = re.search(r"(\d+\.\s*Ausschreibung[^.]{0,40}Sparkling Science 2\.0)", text)
    amt = Amount()
    try:
        faq = _text(http.get(base + "/ausschreibungen/faqs"), "main")
        ext = extract_amounts(faq + " " + text)
        base_max = re.search(r"maximale\s+Förderbetrag\s+beträgt\s+(\d{3}\.\d{3})", faq + " " + text)
        addons = [parse_number(x, None) for x in re.findall(r"max\.\s*(\d{3}\.\d{3})\s*Euro", faq)]
        addons = [x for x in addons if x]
        if base_max or addons:
            # The call text (PDF) sets the base maximum at €350,000; the FAQ lists the raised caps.
            amt.max_eur = parse_number(base_max[1], None) if base_max else 350000.0
            amt.source = "extracted from text" if base_max else "computed"
            if addons:
                amt.note = f"up to €{max(addons):,.0f} if the extra criteria are met".replace(",", ".")
        else:
            amt = ext
    except Exception as e:  # noqa: BLE001
        log.debug("Sparkling Science FAQ: %s", e)
    if not amt.max_eur:
        amt = Amount(max_eur=350000, source="computed", note="per call text (PDF): max. €350,000, up to €420,000 with add-ons")
    title = (m_title[1] if m_title else "Sparkling Science 2.0 – Ausschreibung")
    return [Call(
        id=f"oead:sparkling-science-{end.year}",
        title=title, url=url,
        source="OeAD · Sparkling Science 2.0 (BMFWF)", funder="OeAD on behalf of BMFWF",
        programme="Citizen Science – research with schools",
        status="open" if not start or start <= today() else "forthcoming",
        opening_date=iso(start), deadline=iso(end), deadlines=[iso(end)],
        deadline_note=f"until {m_end[1]}{', ' + m_end[2] + ' Uhr' if m_end[2] else ''}",
        description=text[:6000], amount=amt,
        eligibility="Austrian research institutions (universities, FHs, non-university research) with schools as partners",
        language="de",
    )]


# --------------------------------------------------------------------------- netidee

def netidee(http: Http) -> list[Call]:
    """netidee (Internet Foundation Austria). Only emits a call when a deadline is announced."""
    out = []
    home = http.get("https://www.netidee.at/")
    soup = BeautifulSoup(home, "html.parser")
    for col in soup.select("div.cta-column--description, .cta-column"):
        h = col.find_previous("h3") or col.find("h3")
        label = h.get_text(" ", strip=True) if h else "Call"
        txt = squash(col.get_text(" "))
        if re.search(r"noch nicht fixiert|derzeit kein|geschlossen", txt, re.I):
            continue
        ds = [d for d in find_dates(txt) if d >= today()]
        if not ds:
            continue
        kind = label.lower()
        detail = "https://www.netidee.at/einreichen/" + ("stipendium" if "stipend" in kind else "science" if "science" in kind else "projekt")
        dtext = _text(http.get(detail), "main")
        amt = extract_amounts(dtext)
        out.append(Call(
            id=f"netidee:{kind}-{ds[-1].year}", title=f"netidee Call – {label}", url=detail,
            source="netidee · Internet Foundation Austria", funder="Internet Privatstiftung Austria",
            status="open", deadline=iso(ds[-1]), deadlines=[iso(d) for d in ds],
            description=dtext[:6000], amount=amt, language="de",
            eligibility="Open-source internet projects from Austria (individuals, companies, research)",
        ))
    log.info("netidee: %d open calls", len(out))
    return out


# --------------------------------------------------------------------------- Interreg

def _table_rows(html: str) -> list[list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table tr"):
        cells = [squash(td.get_text(" ")) for td in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)
    return rows


BAYAUT_AMOUNTS = {
    "groß": (35000, None, "total eligible costs > €35,000, 75% ERDF"),
    "mittel": (35000, 100000, "total eligible costs €35k–100k, 75% ERDF, via EUREGIOs"),
    "klein": (None, 35000, "total eligible costs ≤ €35,000, 75% ERDF, via EUREGIOs"),
    "people": (None, 5000, "≤ €5,000, via EUREGIOs"),
    "p2p": (None, 5000, "≤ €5,000, via EUREGIOs"),
}


def interreg_bayaut(http: Http) -> list[Call]:
    url = "https://www.interreg-bayaut.net/einreichfristen/"
    calls = []
    for cells in _table_rows(http.get(url)):
        if len(cells) < 2 or re.search(r"Projektart", cells[0], re.I):
            continue
        ds = [d for d in find_dates(cells[1]) if d >= today()]
        if not ds:
            continue
        kind = cells[0]
        k = kind.lower()
        if "mittel" in k and "klein" in k:
            lo, hi, note = None, 100000, "Kleinprojekte ≤ €35k, Mittelprojekte €35k–100k total eligible costs; 75% ERDF; via EUREGIOs"
        else:
            lo, hi, note = next((v for kk, v in BAYAUT_AMOUNTS.items() if kk in k), (None, None, None))
        amt = Amount(min_eur=lo, max_eur=hi, funding_rate="75% ERDF", note=note,
                     source="official field" if (lo or hi) else "not stated")
        calls.append(Call(
            id=f"interreg-bayaut:{re.sub(r'\W+', '-', kind.lower())}-{ds[0].isoformat()}",
            title=f"Interreg Bayern–Österreich: {kind}", url=url,
            source="Interreg · Bayern–Österreich", funder="Interreg VI-A Bayern–Österreich (ERDF)",
            programme="Cross-border cooperation AT–BY 2021–2027", status="open",
            deadline=iso(ds[0]), deadlines=[iso(d) for d in ds],
            deadline_note=f"Gremium: {cells[2]}" if len(cells) > 2 else None,
            description=(f"Cross-border cooperation projects between Bavaria and Austria ({kind}). "
                         "Joint projects with at least one Bavarian and one Austrian partner in the programme area "
                         "(Upper Austria is eligible), e.g. innovation, education, culture, tourism, digital solutions "
                         "and people-to-people cooperation. Funding: up to 75% ERDF of eligible costs. "
                         "Mittel-/Kleinprojekte and People2People are handled by the EUREGIOs."),
            amount=amt, language="de",
            eligibility="Public bodies, research & education institutions, NGOs and companies in the AT–BY border region (incl. Upper Austria)",
        ))
    log.info("Interreg BY-AT: %d upcoming deadlines", len(calls))
    return calls


def interreg_atcz(http: Http) -> list[Call]:
    url = "https://interreg.at-cz.eu/at/termine/einreichfristen-und-behandlung-der-projektantrage"
    calls = []
    for cells in _table_rows(http.get(url)):
        ds = [d for d in find_dates(cells[0]) if d >= today()] if cells else []
        if not ds:
            continue
        calls.append(Call(
            id=f"interreg-atcz:{ds[0].isoformat()}",
            title="Interreg Österreich–Tschechien: Einreichfrist Projektanträge", url=url,
            source="Interreg · Österreich–Tschechien", funder="Interreg VI-A Österreich–Tschechien (ERDF)",
            programme="Cross-border cooperation AT–CZ 2021–2027", status="open",
            deadline=iso(ds[0]), deadlines=[iso(ds[0])],
            deadline_note=f"Begleitausschuss: {cells[1]}" if len(cells) > 1 else cells[0],
            description=("Cross-border projects between Austria (incl. Upper Austria) and the Czech Republic: research & "
                         "innovation, education, culture and sustainable tourism, environment, public administration. "
                         "Großprojekte > €200,000 total cost; Mittelprojekte €30k/50k–200k. Small projects up to "
                         "€50,000 (culture/tourism) or €30,000 (people-to-people) via the regional Kleinprojektefonds "
                         "(RMOÖ for Upper Austria), rolling."),
            amount=Amount(min_eur=30000, max_eur=None, funding_rate="up to 80% ERDF",
                          note="Mittelprojekte €30–200k; Großprojekte > €200k total cost",
                          source="official field"),
            language="de",
            eligibility="Public and non-profit bodies, research & education institutions in the AT–CZ border region; Czech partner required",
        ))
    log.info("Interreg AT-CZ: %d upcoming deadlines", len(calls))
    return calls


# --------------------------------------------------------------------------- aws

def aws_poc(http: Http) -> list[Call]:
    url = "https://www.aws.at/aws-proof-of-concept/"
    text = _text(http.get(url), "main")
    stich = re.search(r"Antragstichtage?\s+20\d\d:?\s*([^A-Z]{0,80})", text)
    ds = [d for d in find_dates(stich[1]) if d >= today()] if stich else []
    exhausted = re.search(r"ausgeschöpft[^.]*?ab\s+dem\s+(\d{1,2}\.\s*\w+\s+20\d\d)", text, re.I)
    reopen = find_dates(exhausted[1])[0] if exhausted and find_dates(exhausted[1]) else None
    amt = Amount(min_eur=20000, max_eur=80000, funding_rate="75%",
                 note="KLEIN max. €20k · GROSS max. €80k", source="extracted from text")
    ext = extract_amounts(text)
    if ext.max_eur and ext.max_eur != amt.max_eur:
        amt.max_eur = ext.max_eur
    if ds:
        status, deadline, note = "open", ds[0], "Antragsstichtag"
    elif reopen:
        status, deadline, note = "forthcoming", None, f"2026 budget exhausted – new applications from {reopen.strftime('%d.%m.%Y')}"
    else:
        status, deadline, note = "rolling", None, "Stichtage are announced on the programme page"
    return [Call(
        id="aws:proof-of-concept", title="aws Proof of Concept (Universitäten & Fachhochschulen)", url=url,
        source="aws · Austria Wirtschaftsservice", funder="aws (BMFWF)",
        programme="Spezialprogramme Universitäten", status=status,
        opening_date=iso(reopen) if reopen else None, deadline=iso(deadline),
        deadlines=[iso(d) for d in ds], deadline_note=note,
        description=("Funds the validation of research results from universities and universities of applied sciences "
                     "towards commercial exploitation (prototypes, technical feasibility, IP strategy, market validation). "
                     + text[:5000]),
        amount=amt, language="de",
        eligibility="Austrian universities and Fachhochschulen (incl. FH OÖ)",
    )]


# --------------------------------------------------------------------------- entry

PARSERS = {
    "FWF": fwf,
    "Sparkling Science": sparkling_science,
    "netidee": netidee,
    "Interreg BY-AT": interreg_bayaut,
    "Interreg AT-CZ": interreg_atcz,
    "aws PoC": aws_poc,
}


def scrape(http: Http) -> list[Call]:
    calls = []
    for name, fn in PARSERS.items():
        try:
            calls += fn(http)
        except Exception as e:  # noqa: BLE001 - keep other parsers running
            log.warning("%s failed: %s", name, e)
    return calls
