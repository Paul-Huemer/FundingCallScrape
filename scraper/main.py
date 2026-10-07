"""Run all sources -> score -> summarise -> write data/calls.json + dashboard/data.js.

    python -m scraper.main                # full run (HTTP cache 12 h)
    python -m scraper.main --fresh        # ignore HTTP cache
    python -m scraper.main --no-ai        # extractive summaries only
    python -m scraper.main --only eu,ffg  # subset of sources
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from collections import Counter
from datetime import date, datetime
from urllib.parse import urlsplit

from .common import ROOT, Http, save_json, today
from .scoring import Scorer
from .summarize import Summarizer
from .sources import aggregators, austria, eu_portal, ffg, international, watchlist

log = logging.getLogger("scraper")
# medium and high sit above the dashboard's FIT_MIN (55): curated funders are listed by default, "low" ones under "Show lower-fit calls"
FIT_FLOOR = {"high": 66, "medium": 56, "low": 30}
LABELS = {"eu": "EU Funding & Tenders portal", "ffg": "FFG", "austria": "FWF, OeAD, aws, Interreg, netidee",
          "international": "EIT",
          "aggregators": "call aggregators (On the Move, S+T+ARTS, EUREKA)", "watchlist": "foundations & niche funders"}


def run(args) -> dict:
    profile = json.loads((ROOT / "config" / "lab_profile.json").read_text(encoding="utf-8"))
    http = Http(ttl_hours=0 if args.fresh else 12)
    only = set(args.only.split(",")) if args.only else None

    sources = {
        "eu": lambda: eu_portal.scrape(http, profile["eu_search_terms"]),
        "ffg": lambda: ffg.scrape(http),
        "austria": lambda: austria.scrape(http),
        "international": lambda: international.scrape(http),
        "aggregators": lambda: aggregators.scrape(http),
        "watchlist": lambda: watchlist.scrape(http),
    }
    calls, report = [], {}
    for name, fn in sources.items():
        if only and name not in only:
            continue
        t0 = time.time()
        log.info("Checking %s ...", LABELS.get(name, name))
        try:
            got = fn()
            report[name] = {"ok": True, "found": len(got), "seconds": round(time.time() - t0, 1)}
            calls += got
        except Exception as e:  # noqa: BLE001 - one broken site must not kill the run
            log.exception("source %s failed", name)
            report[name] = {"ok": False, "error": str(e)[:300]}

    # de-duplicate (same id, or same title+deadline across sources)
    uniq, seen = [], set()
    for c in calls:
        k2 = (c.title.lower().strip(), c.deadline)
        if c.id in seen or k2 in seen:
            continue
        seen |= {c.id, k2}
        uniq.append(c)

    watch_fit = watchlist.curated_fit()
    scorer = Scorer(profile)
    for c in uniq:
        scorer.score(c)
        if c.id.startswith("watch:"):          # curated funders: keep, with a floor from the curated fit
            c.relevance = max(c.relevance, FIT_FLOOR.get(watch_fit.get(c.id, ""), 0))
    min_rel = profile["scoring"]["store_min_relevance"]
    kept = [c for c in uniq if (c.relevance >= min_rel or c.id.startswith("watch:")) and (not c.deadline or c.deadline >= today().isoformat())]
    log.info("%d calls collected, %d unique, %d relevant (>= %d)", len(calls), len(uniq), len(kept), min_rel)

    new_count = mark_first_seen(kept)
    log.info("%d calls are new since the last run", new_count)

    log.info("Writing summaries ...")
    summ = Summarizer(profile, use_ai=not args.no_ai)
    for i, c in enumerate(kept, 1):
        summ.summarize(c)
        if i % 25 == 0:
            summ.save()
            log.info("summarised %d/%d", i, len(kept))
    summ.save()

    kept.sort(key=lambda c: (c.source, c.deadline or "9999-12-31"))
    out = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="minutes"),
        "lab": profile["lab"],
        "areas": [a["label"] for a in profile["areas"]],
        "topics": [{"key": a["key"], "label": a["label"], "short": a.get("short", a["label"])} for a in profile["areas"]],
        "sources_report": report,
        "summary_mode": "ai" if summ.ai_calls or (summ.client is not None) else "extractive",
        "stats": {
            "collected": len(calls), "unique": len(uniq), "relevant": len(kept), "new": new_count,
            "by_source": Counter(c.source for c in kept),
        },
        "calls": [public_record(c) for c in kept],
    }
    save_json(ROOT / "data" / "calls.json", out)
    # The site is public: data.js carries only what the dashboard shows (no lab profile, run report or stats).
    site = {k: out[k] for k in ("generated_at", "topics", "calls")}
    js = "window.DML_DATA = " + json.dumps(site, ensure_ascii=False) + ";\n"
    (ROOT / "dashboard").mkdir(exist_ok=True)
    (ROOT / "dashboard" / "data.js").write_text(js, encoding="utf-8")
    log.info("wrote data/calls.json and dashboard/data.js (%d calls)", len(kept))
    return out


HISTORY = ROOT / "data" / "history.json"

# The dashboard is published (GitHub Pages): never republish personal contact details that
# appear on funders' pages (FFG/OeAD contact persons, phone numbers, e-mail addresses).
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?:\+|00)\d{2}[\s/().-]*\d[\d\s/().-]{5,}\d|\b0\d{2,4}[\s/-]\d{3,}[\d\s/-]{2,}\b")


def scrub(text: str | None) -> str | None:
    if not text:
        return text
    return re.sub(r"\s{2,}", " ", _PHONE.sub("[phone]", _EMAIL.sub("[e-mail]", text)))


# Verbatim call text is republished only where the publisher's terms allow reuse (checked 2026-10-06).
# Everyone else gets title, link, dates, amount and our own summary, which needs no licence.
# host -> credit line shown under the excerpt (the licences ask for attribution and "changes indicated").
EXCERPT_LICENCES = {
    "ec.europa.eu": "© European Union, CC BY 4.0 (Commission Decision 2011/833/EU)",
    "culture.ec.europa.eu": "© European Union, CC BY 4.0 (Commission Decision 2011/833/EU)",
    "digital-skills-jobs.europa.eu": "© European Union, CC BY 4.0 (Commission Decision 2011/833/EU)",
    "www.eit.europa.eu": "© EIT, reuse permitted with acknowledgement of the source",
    "www.fwf.ac.at": "© Austrian Science Fund (FWF), CC BY 4.0",
    "oead.at": "© OeAD",
    "erasmusplus.oead.at": "© OeAD",
    "kulturvermittlung.oead.at": "© OeAD",
    "www.eurekanetwork.org": "© EUREKA, non-commercial use with acknowledgement of the source",
    "wellcome.org": "© Wellcome, CC BY 4.0",
}
NO_SUMMARY = ("No summary: this funder's text may not be republished here, and AI summaries are off "
              "(set ANTHROPIC_API_KEY). Open the official call page.")
# Cascade calls on the EU portal are written by the project consortia, not the Commission: no CC BY.
NO_EXCERPT_SOURCES = ("EU · Cascade",)


def excerpt_credit(c) -> str | None:
    if c.source.startswith(NO_EXCERPT_SOURCES):
        return None
    return EXCERPT_LICENCES.get(urlsplit(c.url).netloc.lower())


def public_record(c) -> dict:
    d = {k: v for k, v in c.to_dict().items() if k not in ("description", "summary_source", "eligibility_public")}
    credit = excerpt_credit(c)
    d["excerpt"] = scrub(c.description[:1500]) if credit else None
    d["excerpt_credit"] = (credit + " · shortened and cleaned up") if credit else None
    if not credit:
        if c.summary_source == "extract":   # extractive summaries are the funder's own sentences
            d["summary"] = NO_SUMMARY
        if c.eligibility_public is not None:
            d["eligibility"] = c.eligibility_public
    for k in ("summary", "fit_reason", "eligibility", "deadline_note"):
        d[k] = scrub(d.get(k))
    return d


def mark_first_seen(calls) -> int:
    """Remember when each call was first found (data/history.json) so the dashboard can sort by
    "newest" and badge new calls (first found in the last 7 days).

    The very first run only records a baseline: those calls are dated by their opening date where
    known and otherwise stay undated (""), and none of them is flagged as new."""
    hist = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else {}
    first_seen: dict = hist.get("first_seen", {})
    seeding = not first_seen
    now = today().isoformat()
    new = 0
    for c in calls:
        if c.id not in first_seen:
            if seeding:
                first_seen[c.id] = c.opening_date if c.opening_date and c.opening_date <= now else ""
            else:
                first_seen[c.id] = now
                new += 1
        c.first_seen = first_seen[c.id] or None
        c.is_new = bool(hist.get("baseline")) and c.first_seen is not None and c.first_seen >= hist["baseline"]             and (today() - date.fromisoformat(c.first_seen)).days <= 7
    save_json(HISTORY, {"baseline": hist.get("baseline", now),
                        "last_run": datetime.now().astimezone().isoformat(timespec="minutes"),
                        "first_seen": first_seen})
    return new


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fresh", action="store_true", help="ignore the HTTP cache")
    ap.add_argument("--no-ai", action="store_true", help="do not call the Claude API for summaries")
    ap.add_argument("--only", help="comma-separated subset of sources: eu,ffg,austria,international,aggregators,watchlist")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    run(args)


if __name__ == "__main__":
    main()
