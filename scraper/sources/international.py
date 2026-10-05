"""International sources with a structured call list (others live in config/watchlist.json).

* EIT aggregator – one static page listing the open calls of all EIT Knowledge & Innovation
  Communities (Culture & Creativity, Digital, Health, Climate-KIC, …) with start/end dates.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..common import Call, Http, extract_amounts, iso, squash, today

log = logging.getLogger("scraper.international")

EIT = "https://www.eit.europa.eu/our-activities/opportunities"
_DMY = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def _dmy(s: str) -> date | None:
    m = _DMY.search(s or "")
    try:
        return date(int(m[3]), int(m[2]), int(m[1])) if m else None
    except ValueError:
        return None


def eit(http: Http) -> list[Call]:
    soup = BeautifulSoup(http.get(EIT), "html.parser")
    calls = []
    for row in soup.select(".views-row"):
        a = row.select_one(".teaser-title a")
        if not a:
            continue
        start = _dmy((row.select_one(".start-date") or a).get_text(" "))
        end = _dmy((row.select_one(".end-date") or a).get_text(" "))
        if end and end < today():
            continue
        kic = squash((row.select_one(".opportunity-kics") or a).get_text(" ")) if row.select_one(".opportunity-kics") else ""
        url = urljoin(EIT, a["href"])
        desc = ""
        try:
            d = BeautifulSoup(http.get(url), "html.parser")
            for t in d(["script", "style", "nav", "footer", "header"]):
                t.decompose()
            node = d.select_one("main") or d.select_one("article") or d
            desc = squash(node.get_text(" "))
        except Exception as e:  # noqa: BLE001
            log.debug("EIT detail %s: %s", url, e)
        title = a.get_text(" ", strip=True)
        calls.append(Call(
            id="eit:" + url.rstrip("/").rsplit("/", 1)[-1],
            title=title, url=url,
            source="EIT · European Institute of Innovation & Technology",
            funder=f"EIT {kic}".strip() if kic and kic != "EIT" else "EIT",
            programme=kic,
            status="open" if not start or start <= today() else "forthcoming",
            opening_date=iso(start), deadline=iso(end), deadlines=[iso(end)] if end else [],
            description=desc[:8000], amount=extract_amounts(desc[:10000]), language="en",
        ))
    log.info("EIT: %d open calls", len(calls))
    return calls


def scrape(http: Http) -> list[Call]:
    out = []
    for name, fn in {"EIT": eit}.items():
        try:
            out += fn(http)
        except Exception as e:  # noqa: BLE001
            log.warning("%s failed: %s", name, e)
    return out
