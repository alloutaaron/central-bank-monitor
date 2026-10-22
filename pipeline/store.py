"""Persistent back-end state kept in the repo (git history is the archive):
data/state.json, data/expectations.json, data/statements/YYYY-MM.jsonl
(every classified item, with source and reason: the audit trail), and the
source-health history used to flag stale sources."""
from __future__ import annotations

import json
from pathlib import Path

from .common import ROOT, read_json, write_json, now_sgt

DATA = ROOT / "data"


def load_state() -> dict:
    return read_json(DATA / "state.json", {}) or {}


def save_state(state: dict):
    write_json(DATA / "state.json", state)


def load_expectations() -> dict:
    return read_json(DATA / "expectations.json", {}) or {}


def save_expectations(ex: dict):
    write_json(DATA / "expectations.json", ex)


def _month_file(month: str) -> Path:
    return DATA / "statements" / f"{month}.jsonl"


def append_statements(rows: list[dict]):
    """Append classified items; one JSON object per line, grouped by month."""
    by_month: dict[str, list] = {}
    for r in rows:
        by_month.setdefault(r["ts"][:7], []).append(r)
    for month, items in by_month.items():
        f = _month_file(month)
        f.parent.mkdir(parents=True, exist_ok=True)
        existing = {json.loads(l)["id"] for l in f.read_text(encoding="utf-8").splitlines() if l.strip()} if f.exists() else set()
        with f.open("a", encoding="utf-8") as fh:
            for r in sorted(items, key=lambda x: x["ts"]):
                if r["id"] not in existing:
                    fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def all_statements(since_month: str = "0000-00") -> list[dict]:
    out = []
    for f in sorted((DATA / "statements").glob("*.jsonl")):
        if f.stem >= since_month:
            out += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    return out


def update_health(log: dict) -> dict:
    """Merge this run's source outcomes into the persistent health record."""
    path = DATA / "source_health.json"
    health = read_json(path, {}) or {}
    stamp = now_sgt().isoformat(timespec="seconds")
    for sid, e in log.items():
        h = health.setdefault(sid, {})
        h["last_run"] = stamp
        h["ok"] = e["ok"]
        if e["ok"]:
            h["last_ok"] = e.get("last_ok", stamp)
            h.pop("error", None)
        else:
            h["error"] = (e.get("errors") or [""])[-1]
    write_json(path, health)
    return health
