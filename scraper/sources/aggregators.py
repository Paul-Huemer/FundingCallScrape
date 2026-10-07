"""Call aggregators: sites that list many calls from many funders on one page.

* On the Move – worldwide culture-mobility funding (residencies, project funding, commissions).
  Only the categories that touch the lab (digital / new media, technology, art & science, cultural
  heritage, education, disability) are read, through their category pages (/disciplines/…, /topics/…):
  robots.txt disallows the filtered list URLs (?f[0]=…). Scoring drops what does not fit.
* S+T+ARTS – the EC's science-technology-arts initiative: residencies and open calls of its projects.
* EUREKA – Eurostars, EUREKA Clusters (ITEA, CELTIC-NEXT, …) and Network Projects, funded in Austria
  through FFG. Company-led, so the lab joins as research partner. Investment-readiness pitch sessions
  are skipped.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..common import Amount, Call, Http, extract_amounts, find_dates, iso, squash, today

log = logging.getLogger("scraper.aggregators")


def _text(http: Http, url: str, selector: str | None = None) -> str:
    try:
        soup = BeautifulSoup(http.get(url), "html.parser")
    except Exception as e:  # noqa: BLE001 - list the call even without its detail text
        log.debug("detail %s: %s", url, e)
        return ""
    for t in soup(["script", "style", "svg", "noscript", "nav", "footer", "header"]):
        t.decompose()
    node = (soup.select_one(selector) if selector else None) or soup.select_one("main") or soup.select_one("article") or soup
    return squash(node.get_text(" "))


# --------------------------------------------------------------------------- On the Move

OTM = "https://on-the-move.org"
OTM_CATEGORIES = {                  # category pages; newest posts first, expired ones marked
    "/disciplines/digital-new-media": "Digital / New Media",
    "/disciplines/cultural-heritage": "Cultural Heritage",
    "/topics/technology-new-media": "Technology & New Media",
    "/topics/art-sciences": "Art & Sciences",
    "/topics/education-training": "Education & Training",
    "/topics/disability": "Disability",
}


def on_the_move(http: Http) -> list[Call]:
    seen, calls = set(), []
    for path, label in OTM_CATEGORIES.items():
        for page in range(3):
            soup = BeautifulSoup(http.get(OTM + path, params={"page": page} if page else None), "html.parser")
            items = soup.select("li.list")
            for li in items:
                a = li.select_one("a.list-link")
                if not a or a["href"] in seen or "expired" in li.get("class", []):
                    continue
                seen.add(a["href"])
                url = urljoin(OTM, a["href"])
                try:                    # category pages show no deadline; the call page's first <time> is it
                    t = BeautifulSoup(http.get(url), "html.parser").select_one("time[datetime]")
                except Exception:  # noqa: BLE001
                    t = None
                deadline = t["datetime"][:10] if t else None
                if deadline and deadline < today().isoformat():
                    continue
                title = squash((li.select_one(".list_title") or a).get_text(" "))
                kind = squash((li.select_one(".list_meta_news-type") or li).get_text(" ")) if li.select_one(".list_meta_news-type") else ""
                desc = _text(http, url, "article.node")
                head = _text(http, url, "aside")
                open_for = re.search(r"Open for:\s*(.{0,120}?)(?:Destination|Read this|$)", head)
                who = squash(open_for.group(1)) if open_for else ""
                individuals_only = who and "Organisation" not in who and "Collective" not in who
                calls.append(Call(
                    id="otm:" + a["href"].rstrip("/").rsplit("/", 1)[-1],
                    title=title, url=url,
                    source="Open calls · On the Move (arts & culture)",
                    funder="via On the Move", programme=kind,
                    status="open", deadline=deadline, deadlines=[deadline] if deadline else [],
                    description=f"{label}. {desc}"[:8000],
                    amount=extract_amounts(desc[:8000]),
                    eligibility=("⚠ Individuals only – lab members can apply personally. " if individuals_only else "") + (f"Open for: {who}" if who else ""),
                    keywords=[label, kind],
                    language="en",
                ))
            if not soup.select_one(".pager__item--next"):
                break
    log.info("On the Move: %d open calls in lab-related categories", len(calls))
    return calls


# --------------------------------------------------------------------------- S+T+ARTS

STARTS = "https://starts.eu/calls/"


def starts(http: Http) -> list[Call]:
    soup = BeautifulSoup(http.get(STARTS), "html.parser")
    calls = []
    for art in soup.select("article"):
        a = art.select_one(".uagb-post__title a, h4 a, h3 a")
        if not a:
            continue
        date_txt = squash((art.select_one(".date") or art).get_text(" ")) if art.select_one(".date") else ""
        stated = find_dates(date_txt)
        dls = [d for d in stated if d >= today()]
        if stated and not dls:                  # "Closes: <past date>"
            continue
        url = a["href"].replace("http://", "https://")
        desc = _text(http, url, ".entry-content")
        if not dls:
            dls = [d for d in find_dates(desc) if d >= today()][:1]
        calls.append(Call(
            id="starts:" + url.rstrip("/").rsplit("/", 1)[-1],
            title=squash(a.get_text(" ")), url=url,
            source="Open calls · S+T+ARTS (science, technology & arts)",
            funder="European Commission – S+T+ARTS initiative",
            programme=squash((art.select_one(".calltype") or a).get_text(" ")) if art.select_one(".calltype") else "",
            status="open" if dls else "rolling",
            deadline=iso(dls[0]) if dls else None, deadlines=[iso(d) for d in dls[:2]],
            description=desc[:8000], amount=extract_amounts(desc[:8000]), language="en",
            eligibility="Artists, often in tandem with research or tech partners – the lab can host or partner",
        ))
    log.info("S+T+ARTS: %d open calls", len(calls))
    return calls


# --------------------------------------------------------------------------- EUREKA

EUREKA = "https://www.eurekanetwork.org/programmes-and-calls/"
EUREKA_SKIP = re.compile(r"Investment Readiness|Fast Track|Innowwide", re.I)


def eureka(http: Http) -> list[Call]:
    calls, seen = [], set()
    for page in range(1, 6):
        soup = BeautifulSoup(http.get(EUREKA, params={"status": "open", "paged": page}), "html.parser")
        cards = [d for d in soup.select("div.relative.rounded-lg") if d.select_one("h3")]
        if not cards:
            break
        for card in cards:
            a = card.select_one("a[href]")
            prog = squash(card.select_one("span").get_text(" ")) if card.select_one("span") else ""
            if not a or a["href"] in seen or EUREKA_SKIP.search(prog):
                continue
            seen.add(a["href"])
            dls = [d for d in find_dates(card.get_text(" ")) if d >= today()]
            desc = _text(http, a["href"])
            if desc and "Austria" not in desc:      # Austria (FFG) does not fund this call
                continue
            calls.append(Call(
                id="eureka:" + a["href"].rstrip("/").rsplit("/", 1)[-1],
                title=squash(card.select_one("h3").get_text(" ")), url=a["href"],
                source="Open calls · EUREKA (Eurostars, Clusters, Network Projects)",
                funder="EUREKA network; Austrian partners funded by FFG",
                programme=prog,
                status="open" if dls and dls[0].year < today().year + 3 else "rolling",
                deadline=iso(dls[0]) if dls and dls[0].year < today().year + 3 else None, deadlines=[iso(d) for d in dls[:2]],
                description=desc[:8000], language="en",
                amount=Amount(note="national funding: Austrian partners apply to FFG (research partners up to 50–60%)"),
                eligibility="⚠ Partner role only – company-led consortia; research partners funded through FFG national programmes",
            ))
        if not soup.find("a", href=re.compile(rf"paged={page + 1}")):
            break
    log.info("EUREKA: %d open calls", len(calls))
    return calls


def scrape(http: Http) -> list[Call]:
    out = []
    for name, fn in {"On the Move": on_the_move, "S+T+ARTS": starts, "EUREKA": eureka}.items():
        try:
            out += fn(http)
        except Exception as e:  # noqa: BLE001
            log.warning("%s failed: %s", name, e)
    return out
