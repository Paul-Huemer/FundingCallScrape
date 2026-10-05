"""Keyword-based relevance of a call to the lab profile (transparent and explainable)."""
from __future__ import annotations

import math
import re

from .common import Call


def _compile(term: str) -> re.Pattern:
    term = term.lstrip("~")
    case_sensitive = term.startswith("cs:")
    t = term[3:] if case_sensitive else term
    body = re.escape(t).replace(r"\ ", r"[\s-]+")
    # long terms also match inflections/compounds (e.g. "Museum" -> "Museumsbesuch")
    tail = r"\w*" if len(t) >= 5 and not case_sensitive else r"\b"
    return re.compile(rf"(?<![\w-]){body}{tail}", 0 if case_sensitive else re.I)


class Scorer:
    def __init__(self, profile: dict):
        self.cfg = profile["scoring"]
        self.areas = [
            {**a, "rx": [(_compile(t), t.lstrip("~").removeprefix("cs:"), t.startswith("~")) for t in a["terms"]]}
            for a in profile["areas"]
        ]
        self.weak = self.cfg.get("weak_term_factor", 0.3)
        self.bonus = [(re.compile(k, re.I), v) for k, v in profile.get("programme_bonus", {}).items() if not k.startswith("_")]
        self.neg = [(_compile(t), t) for t in profile.get("negative_terms", [])]
        self.neg_w = profile.get("negative_weight", 2.0)
        self.elig = [_compile(t) for t in profile.get("eligible_applicant_terms", [])]
        self.synergies = profile.get("synergies", [])

    def score(self, c: Call) -> None:
        title = f"{c.title} {c.programme}"
        body = f"{c.description} {' '.join(c.keywords)}"
        tm = self.cfg.get("title_multiplier", 3)
        raw, areas, terms, hit_keys, topics = 0.0, [], set(), set(), {}
        for a in self.areas:
            t_hits = {(lbl, w) for rx, lbl, w in a["rx"] if rx.search(title)}
            b_hits = {(lbl, w) for rx, lbl, w in a["rx"] if rx.search(body)} - t_hits
            f = lambda hs: sum(self.weak if w else 1.0 for _, w in hs)  # noqa: E731
            hits = tm * f(t_hits) + f(b_hits)
            t_hits, b_hits = {l for l, _ in t_hits}, {l for l, _ in b_hits}
            if hits:
                contrib = min(a["weight"] * hits, a["weight"] * 9)
                raw += contrib
                if contrib >= a["weight"]:          # at least one real (non-weak) hit
                    hit_keys.add(a["key"])
                if contrib >= a["weight"] * 2 or t_hits:
                    areas.append(a["label"])
                if contrib >= a["weight"]:      # >= one specific (non-generic) term: tag the topic
                    topics[a["key"]] = round(contrib / a["weight"], 1)   # strength: 1 … 9
                terms |= t_hits | b_hits
        for syn in self.synergies:
            if hit_keys & set(syn["any_of"]) and hit_keys & set(syn["and_any_of"]) and                     (set(syn["any_of"]) & hit_keys) != (set(syn["and_any_of"]) & hit_keys):
                raw += syn["bonus"]
                if syn["label"] not in areas:
                    areas.insert(0, syn["label"])
                for k in syn.get("adds_topics", []):           # e.g. games + education => educational games
                    topics.setdefault(k, 2.0)
        neg_hits = {lbl for rx, lbl in self.neg if rx.search(title)}
        neg_body = {lbl for rx, lbl in self.neg if rx.search(body)} - neg_hits
        raw -= self.neg_w * (tm * len(neg_hits) + 0.5 * len(neg_body))
        raw += sum(v for rx, v in self.bonus if rx.search(c.title))
        raw = max(raw, 0)
        rel = 100 * (1 - math.exp(-raw / self.cfg.get("saturation", 18)))

        # FFG (and others) state eligible applicant types: if research bodies can't apply, the
        # lab can only join as subcontractor/partner -> lower priority, keep visible.
        # (watchlist entries carry curated eligibility; they opt in via "partner_only" instead)
        if c.eligibility and not c.id.startswith("watch:") and not any(rx.search(c.eligibility) for rx in self.elig):
            rel *= self.cfg.get("ineligible_penalty", 0.6)
            c.eligibility = "⚠ Research institutions/FHs are not listed as applicants – partner/subcontractor role only. " + c.eligibility

        c.relevance = int(round(rel))
        c.matched_areas = areas
        c.topics = sorted(topics, key=lambda k: -topics[k])
        c.matched_terms = sorted(terms, key=str.lower)[:20]
