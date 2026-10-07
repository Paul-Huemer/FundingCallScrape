"""Short summaries per call.

With Claude API credentials available (ANTHROPIC_API_KEY or an `ant auth login` profile)
each call gets a 2–3 sentence English summary, a one-line "why it fits the lab" note and a
second opinion on the per-project amount. Results are cached by content hash, so re-runs only
pay for new or changed calls. Without credentials, an extractive summary is used.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from .common import ROOT, Call, extractive_summary

log = logging.getLogger("scraper.summarize")
CACHE = ROOT / "data" / "cache" / "summaries.json"
MODEL = os.environ.get("DML_SUMMARY_MODEL", "claude-opus-5-5")

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "fit_reason", "per_project_min_eur", "per_project_max_eur", "amount_note"],
    "properties": {
        "summary": {"type": "string", "description": "2-3 sentences in English: what is funded, who can apply, format."},
        "fit_reason": {"type": "string", "description": "One sentence: how the Digital Media Lab could contribute, or why the fit is weak."},
        "per_project_min_eur": {"type": ["number", "null"]},
        "per_project_max_eur": {"type": ["number", "null"]},
        "amount_note": {"type": ["string", "null"], "description": "e.g. 'lump sum', 'per partner', 'funding rate 70%'"},
    },
}


class Summarizer:
    def __init__(self, profile: dict, use_ai: bool = True):
        self.profile = profile
        self.cache: dict = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
        self.client = None
        self.ai_calls = 0
        has_creds = any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"))             or (Path.home() / ".config" / "anthropic").exists()
        if use_ai and not has_creds:
            log.info("No Claude credentials found (set ANTHROPIC_API_KEY) – using extractive summaries")
        if use_ai and has_creds:
            try:
                import anthropic
                self.client = anthropic.Anthropic()
                self._anthropic = anthropic
            except Exception as e:  # noqa: BLE001 - missing package or credentials
                log.info("AI summaries disabled (%s); using extractive summaries", e)
                self.client = None

    def _system(self) -> str:
        lab = self.profile["lab"]
        areas = "; ".join(a["label"] for a in self.profile["areas"])
        return (
            f"You brief researchers of the {lab['name']} at {lab['institution']} on funding calls. "
            f"Lab profile: {lab['one_liner']} Research areas: {areas}. "
            "Write plain, specific English. Summaries state what is funded, who may apply and the format "
            "(e.g. consortium size, duration) when the text says so. Never invent amounts: report the "
            "maximum (and minimum) funding ONE project/grant can receive only if the text states it, "
            "otherwise null. Do not report the total call budget as the per-project amount."
        )

    def summarize(self, c: Call) -> None:
        key = hashlib.sha1(f"{MODEL}|{c.id}|{c.title}|{c.description[:6000]}".encode()).hexdigest()
        hit = self.cache.get(key)
        if hit is None and self.client is not None:
            hit = self._ask(c)
            if hit:
                self.cache[key] = hit
        if hit:
            c.summary, c.summary_source = hit["summary"], "ai"
            c.fit_reason = hit.get("fit_reason") or ""
            if c.amount.max_eur is None and hit.get("per_project_max_eur"):
                c.amount.max_eur = float(hit["per_project_max_eur"])
                c.amount.min_eur = hit.get("per_project_min_eur")
                c.amount.source = "AI extracted"
            if hit.get("amount_note") and not c.amount.note:
                c.amount.note = hit["amount_note"][:80]
        else:
            c.summary_source = "curated" if c.summary else "extract"
            c.summary = c.summary or extractive_summary(c.description) or c.title

    def _ask(self, c: Call) -> dict | None:
        text = (f"Title: {c.title}\nProgramme: {c.programme}\nFunder: {c.funder}\n"
                f"Eligibility: {c.eligibility}\nCall text:\n{c.description[:9000]}")
        try:
            resp = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=2000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                system=[{"type": "text", "text": self._system(), "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": text}],
            )
        except self._anthropic.AuthenticationError as e:
            log.warning("No valid Claude credentials (%s) – falling back to extractive summaries", e)
            self.client = None
            return None
        except self._anthropic.APIStatusError as e:
            log.warning("Summary failed for %s: %s", c.id, e)
            return None
        except self._anthropic.APIConnectionError as e:
            log.warning("Claude API unreachable (%s) – extractive summaries", e)
            self.client = None
            return None
        except Exception as e:  # noqa: BLE001 - e.g. unresolvable credentials: never break the scrape
            log.warning("AI summaries disabled after error: %s", e)
            self.client = None
            return None
        if resp.stop_reason == "refusal":
            return None
        self.ai_calls += 1
        out = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return json.loads(out)
        except ValueError:
            return None

    def save(self) -> None:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(self.cache, ensure_ascii=False, indent=0), encoding="utf-8")
