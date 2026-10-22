"""The hand-off between the morning collection job and the language step.

data/inbox/pending.json   items waiting for the language step (cumulative: if a
                          day's language step does not run, items wait)
data/outbox/*.json        the language step's results (written by the Claude
                          routine, or by the API path when a key is set)
data/outbox/applied/      results already merged by pipeline.finalize
"""
from __future__ import annotations

import datetime as dt

from .common import ROOT, now_sgt, read_json, write_json

INBOX = ROOT / "data" / "inbox" / "pending.json"
OUTBOX = ROOT / "data" / "outbox"
CAP_HEADLINES, CAP_DOCS, CAP_EXPECT = 900, 30, 220
DOC_CHARS = 12000


def load() -> dict:
    p = read_json(INBOX, None) or {}
    for k in ("headlines", "documents", "expectations"):
        p.setdefault(k, [])
    return p


def save(p: dict):
    p["generated"] = now_sgt().isoformat(timespec="minutes")
    p["headlines"] = sorted(p["headlines"], key=lambda x: x["ts"])[-CAP_HEADLINES:]
    p["documents"] = sorted(p["documents"], key=lambda x: x.get("date") or "")[-CAP_DOCS:]
    p["expectations"] = p["expectations"][:CAP_EXPECT]
    write_json(INBOX, p)


def add_headlines(p: dict, items: list[dict]):
    have = {x["id"] for x in p["headlines"]}
    for x in items:
        if x["id"] not in have:
            p["headlines"].append({k: x.get(k) for k in ("id", "ts", "source", "kind", "text", "url", "bank_hint")})
            have.add(x["id"])


def add_documents(p: dict, docs: list[dict]):
    have = {x["id"] for x in p["documents"]}
    for d in docs:
        if d["id"] not in have:
            p["documents"].append({"id": d["id"], "bank": d["bank"], "title": d["title"], "date": d["date"], "lang": d["lang"],
                                   "url": d["url"], "text": (d.get("text") or "")[:DOC_CHARS]})
            have.add(d["id"])


def set_expectation_tasks(p: dict, tasks: list[dict]):
    """Replace tasks for the same meeting (fresh headlines each day)."""
    by_id = {t["id"]: t for t in p["expectations"]}
    for t in tasks:
        by_id[t["id"]] = t
    # Upcoming meetings first, then the backlog of past ones (oldest first).
    today = dt.date.today().isoformat()
    p["expectations"] = sorted(by_id.values(), key=lambda t: (t["date"] < today, t["date"] if t["date"] >= today else "", t["date"]))
