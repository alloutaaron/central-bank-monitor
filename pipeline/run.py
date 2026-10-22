"""Daily refresh (and one-off backfill). Usage:
    python -m pipeline.run                 # daily
    python -m pipeline.run --backfill 2026-04-01
Never aborts on a single failed source: failures are recorded and shown as
stale on the page."""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import traceback

from . import consensus, llm, meetings, news, official_docs, spectrum, store, telegram, build
from .common import LOG, ROOT, SGT, now_sgt, read_json, today_sgt

CFG = read_json(ROOT / "config" / "banks.json", {})


def _statement_rows(items: list[dict], results: list[dict]) -> list[dict]:
    by_id = {r["id"]: r for r in results or []}
    rows = []
    for it in items:
        r = by_id.get(it["id"])
        if not r:
            continue
        rows.append({"id": it["id"], "ts": it["ts"], "source": it["source"], "kind": it["kind"],
                     "evidence": it["kind"], "raw": it["text"], "relevant": r["relevant"], "bank": r["bank"],
                     "speaker": r["speaker"], "role": r["role"], "type": r["kind"], "text": r["paraphrase"],
                     "stance": r["stance"], "score": r["score"], "reason": r["reason"],
                     "decision_bp": r.get("decision_bp"), "decision_level": r.get("decision_level"),
                     "classified": now_sgt().isoformat(timespec="seconds"), "model": llm.MODEL})
    return rows


def classify(items: list[dict]) -> list[dict]:
    if not items or not llm.available():
        return []
    res = llm.classify_headlines([{"id": x["id"], "ts": x["ts"][:16].replace("T", " "), "text": x["text"]} for x in items])
    return _statement_rows(items, res or [])


def process_docs(docs: list[dict]) -> list[dict]:
    rows = []
    for d in docs:
        res = llm.process_document(d["bank"], d["title"], d["date"], d["lang"], d["text"]) if llm.available() else None
        if not res:
            continue
        rows.append({"id": d["id"], "ts": f"{d['date']}T12:00+08:00", "date_only": True, "source": "official", "kind": "official",
                     "evidence": "official", "url": d["url"], "title": d["title"], "lang": d["lang"],
                     "relevant": res["relevant"], "bank": d["bank"], "speaker": res["speaker"], "role": res["role"],
                     "type": "remark", "text": " ".join(res["points"][:3]), "stance": res["stance"], "score": res["score"],
                     "reason": res["reason"], "classified": now_sgt().isoformat(timespec="seconds"), "model": llm.MODEL})
    return rows


def decision_watch(rows: list[dict], recs: list[dict], today: dt.date) -> dict:
    """Wire-reported decisions for meetings in the last 3 days that official
    data has not caught up with yet (marked as wire-sourced)."""
    out = {}
    pending = {r["id"]: r for r in recs if r["type"] == "meeting" and not r.get("decision")
               and 0 <= (today - dt.date.fromisoformat(r["date"])).days <= 3}
    for row in rows:
        if row.get("type") != "decision" or not row.get("relevant"):
            continue
        mid = f"{row['bank']}-{row['ts'][:10]}"
        m = re.search(r"[-+]?\d+", row.get("decision_bp") or "")
        if mid in pending and m:
            mv = int(m.group(0))
            lvl = (row.get("decision_level") or "").strip()
            lvl = (lvl + "%") if lvl and not lvl.endswith("%") else lvl
            out[mid] = {"move_bp": mv, "label": ("Hold" + (f" at {lvl}" if lvl else "")) if mv == 0 else f"{mv:+d}bp" + (f" to {lvl}" if lvl else ""),
                        "source": f"{row['source']} (wire report; official data pending)", "source_kind": "wire"}
    return out


def daily(lookback_hours: int = 36):
    today = today_sgt()
    state = store.load_state()
    rows = []
    # 1. Speech feed: Telegram + reputable-news headlines, classified by Claude.
    items = []
    try:
        items += telegram.collect(state, lookback_hours=lookback_hours)
    except Exception as e:
        LOG.fail("TELEGRAM:collector", f"{type(e).__name__}: {e}")
    for code in CFG["order"]:
        items += news.remarks(CFG["banks"][code]["news_name"], code, days=2)
    seen = set(state.get("seen_items", []))
    items = [x for x in items if x["id"] not in seen]
    rows += classify(items)
    # 2. Official speeches/statements (original language, translated).
    processed = set(state.get("processed_docs", []))
    since = (today - dt.timedelta(days=4)).isoformat()
    docs = official_docs.collect(processed, since)
    doc_rows = process_docs(docs)
    rows += doc_rows
    if llm.available():
        state["seen_items"] = sorted(seen | {x["id"] for x in items})[-20000:]
        state["processed_docs"] = sorted(processed | {d["id"] for d in docs})[-5000:]
    store.append_statements(rows)
    # 3. Meetings, expectations, decisions.
    ex = store.load_expectations()
    recs = meetings.build(today=today, expectations=ex)
    ff = consensus.forex_factory()
    ex = consensus.update(ex, recs, today, ff=ff)
    store.save_expectations(ex)
    consensus.archive_speeches(ff)
    watch = decision_watch(store.all_statements((today - dt.timedelta(days=4)).isoformat()[:7]), recs, today)
    recs = meetings.build(today=today, expectations=ex, watch=watch)
    store.save_state(state)
    return finish(recs, today)


def backfill(since: str, telegram_days: int = 21):
    """One-off: news headlines in two-week windows since `since`, Telegram for
    the last `telegram_days`, and expectations for past meetings."""
    today = today_sgt()
    state = store.load_state()
    start = dt.date.fromisoformat(since)
    items = telegram.collect(state, lookback_hours=24 * telegram_days)
    d = start
    while d < today:
        w = (d.isoformat(), min(today, d + dt.timedelta(days=14)).isoformat())
        for code in CFG["order"]:
            items += news.remarks(CFG["banks"][code]["news_name"], code, window=w)
        d += dt.timedelta(days=14)
    uniq = {x["id"]: x for x in items}
    items = list(uniq.values())
    print(f"backfill: {len(items)} headlines to classify", flush=True)
    rows = classify(items)
    processed = set(state.get("processed_docs", []))
    docs = official_docs.collect(processed, since)
    print(f"backfill: {len(docs)} official documents", flush=True)
    rows += process_docs(docs)
    state["seen_items"] = sorted(set(state.get("seen_items", [])) | set(uniq))[-20000:]
    state["processed_docs"] = sorted(processed | {x["id"] for x in docs})[-5000:]
    store.append_statements(rows)
    ex = store.load_expectations()
    recs = meetings.build(today=today, expectations=ex)
    ex = consensus.backfill(ex, recs, today)
    ex = consensus.update(ex, recs, today)
    store.save_expectations(ex)
    store.save_state(state)
    recs = meetings.build(today=today, expectations=ex)
    return finish(recs, today)


def finish(recs: list[dict], today: dt.date):
    statements = store.all_statements()
    spec = spectrum.build(statements, today)
    health = store.update_health(LOG.as_dict())
    build.write_site(recs, statements, spec, health, today, ai={"enabled": llm.available(), **llm.USAGE, "cost_usd": llm.cost_usd()})
    print(f"done: {len(recs)} calendar items, {sum(1 for s in statements if s.get('relevant'))} feed items, "
          f"AI calls {llm.USAGE['calls']} (~US${llm.cost_usd()}), failed sources: "
          f"{sorted(k for k, v in LOG.as_dict().items() if not v['ok'])}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", metavar="YYYY-MM-DD")
    ap.add_argument("--lookback-hours", type=int, default=36)
    a = ap.parse_args()
    try:
        backfill(a.backfill) if a.backfill else daily(a.lookback_hours)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
