"""Merges the language step's results (data/outbox/*.json) and rebuilds the
page from the morning snapshot, without re-fetching any source.

    python -m pipeline.finalize
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil

from . import inbox, meetings, store
from .common import ROOT, now_sgt, read_json, today_sgt

SNAPSHOT = ROOT / "data" / "snapshot.json"


def _rows_from_headlines(results: list[dict], items: dict) -> list[dict]:
    rows = []
    for r in results:
        it = items.get(r.get("id"))
        if not it:
            continue
        rows.append({"id": it["id"], "ts": it["ts"], "source": it["source"], "kind": it["kind"], "evidence": it["kind"],
                     "raw": it["text"], "url": it.get("url"), "relevant": bool(r.get("relevant")), "bank": r.get("bank"),
                     "speaker": r.get("speaker", ""), "role": r.get("role", ""), "type": r.get("kind"),
                     "text": r.get("paraphrase", ""), "stance": r.get("stance", "neutral"), "score": r.get("score", 0),
                     "reason": r.get("reason", ""), "decision_bp": r.get("decision_bp", ""), "decision_level": r.get("decision_level", ""),
                     "classified": now_sgt().isoformat(timespec="seconds"), "model": "claude (routine)"})
    return rows


def _rows_from_documents(results: list[dict], docs: dict) -> list[dict]:
    rows = []
    for r in results:
        d = docs.get(r.get("id"))
        if not d:
            continue
        rows.append({"id": d["id"], "ts": f"{d['date']}T12:00+08:00", "date_only": True, "source": "official", "kind": "official",
                     "evidence": "official", "url": d["url"], "title": d["title"], "lang": d["lang"], "relevant": bool(r.get("relevant")),
                     "bank": d["bank"], "speaker": r.get("speaker", ""), "role": r.get("role", ""), "type": "remark",
                     "text": " ".join((r.get("points") or [])[:3]), "stance": r.get("stance", "neutral"), "score": r.get("score", 0),
                     "reason": r.get("reason", ""), "classified": now_sgt().isoformat(timespec="seconds"), "model": "claude (routine)"})
    return rows


def apply_outbox() -> int:
    pend = inbox.load()
    heads = {x["id"]: x for x in pend["headlines"]}
    docs = {x["id"]: x for x in pend["documents"]}
    tasks = {x["id"]: x for x in pend["expectations"]}
    ex = store.load_expectations()
    state = store.load_state()
    none_found = set(state.get("expect_none", []))
    files = sorted(p for p in inbox.OUTBOX.glob("*.json"))
    done_h, done_d, done_e, rows = set(), set(), set(), []
    for f in files:
        res = json.loads(f.read_text(encoding="utf-8"))
        rows += _rows_from_headlines(res.get("headlines", []), heads)
        rows += _rows_from_documents(res.get("documents", []), docs)
        done_h |= {r.get("id") for r in res.get("headlines", [])}
        done_d |= {r.get("id") for r in res.get("documents", [])}
        for r in res.get("expectations", []):
            t = tasks.get(r.get("id"))
            if not t:
                continue
            done_e.add(t["id"])
            if r.get("found") and re.fullmatch(r"[+-]?\d+", (r.get("move_bp") or "").strip()):
                mv = int(r["move_bp"])
                past = t["date"] < today_sgt().isoformat()
                ex[t["id"]] = {"move_bp": mv, "label": "Hold" if mv == 0 else f"{mv:+d}bp", "basis": r.get("basis", ""),
                               "outlets": (r.get("outlets") or [])[:4], "as_of": t.get("as_of") or today_sgt().isoformat(),
                               "kind": "news", "frozen": past}
            elif t["date"] < today_sgt().isoformat():
                none_found.add(t["id"])     # past meeting: no poll found, do not ask again
        dest = inbox.OUTBOX / "applied"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), dest / f.name)
    store.append_statements(rows)
    store.save_expectations(ex)
    state["expect_none"] = sorted(none_found)
    store.save_state(state)
    pend["headlines"] = [x for x in pend["headlines"] if x["id"] not in done_h]
    pend["documents"] = [x for x in pend["documents"] if x["id"] not in done_d]
    pend["expectations"] = [x for x in pend["expectations"] if x["id"] not in done_e]
    inbox.save(pend)
    return len(files)


def rebuild():
    from .run import decision_watch, finish
    today = today_sgt()
    recs = read_json(SNAPSHOT, []) or []
    ex = store.load_expectations()
    watch = decision_watch(store.all_statements((today - dt.timedelta(days=4)).isoformat()[:7]), recs, today)
    meetings.annotate(recs, ex, watch, today)
    finish(recs, today, language_step=True)


if __name__ == "__main__":
    n = apply_outbox()
    print(f"applied {n} outbox file(s)")
    rebuild()
