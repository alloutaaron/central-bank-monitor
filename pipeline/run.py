"""Collection job, run every 15 minutes. Usage:
    python -m pipeline.run                       # one refresh
    python -m pipeline.run --backfill 2026-04-01 # also collect news headlines since that date
Collects every source, builds the calendar and rates, and turns headlines and
official speeches into feed items with plain rules (pipeline/rules.py; no AI).
Never aborts on one failed source: failures are recorded and shown as stale."""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import traceback

from . import build, check, consensus, inbox, meetings, news, official_docs, rules, spectrum, store, telegram
from .common import LOG, ROOT, now_sgt, read_json, write_json, today_sgt

CFG = read_json(ROOT / "config" / "banks.json", {})
SNAPSHOT = ROOT / "data" / "snapshot.json"
BLOCKED = {"RBA": "https://www.rba.gov.au/", "RBNZ": "https://www.rbnz.govt.nz/", "BSP": "https://www.bsp.gov.ph/",
           "BNM": "https://www.bnm.gov.my/speeches-interviews"}


def access_probe():
    """Whether sites that refuse automated access have become reachable (kept
    apart from the stale-source list, since they fail by design)."""
    from .common import session
    out = {}
    for bank, url in BLOCKED.items():
        try:
            r = session().get(url, timeout=20)
            out[bank] = {"status": r.status_code, "bytes": len(r.content)}
        except Exception as e:
            out[bank] = {"error": type(e).__name__}
    write_json(ROOT / "data" / "access_probe.json", {"checked": now_sgt().isoformat(timespec="minutes"), "sites": out})


def decision_watch(rows: list[dict], recs: list[dict], today: dt.date) -> dict:
    """Wire-reported decisions for meetings in the last 3 days that official
    data has not caught up with yet (labelled as wire-sourced)."""
    out = {}
    pending = {r["id"]: r for r in recs if r["type"] == "meeting" and not r.get("decision_official")
               and 0 <= (today - dt.date.fromisoformat(r["date"])).days <= 3}
    for row in rows:
        if row.get("type") != "decision" or not row.get("relevant"):
            continue
        day = dt.date.fromisoformat(row["ts"][:10])   # SGT can be a day after the local meeting date (e.g. the Fed)
        mid = next((f"{row['bank']}-{d}" for d in (day, day - dt.timedelta(days=1)) if f"{row['bank']}-{d}" in pending), None)
        m = re.search(r"[-+]?\d+", row.get("decision_bp") or "")
        if mid and m:
            mv = int(m.group(0))
            lvl = (row.get("decision_level") or "").strip()
            lvl = (lvl + "%") if lvl and not lvl.endswith("%") else lvl
            out[mid] = {"move_bp": mv, "label": ("Hold" + (f" at {lvl}" if lvl else "")) if mv == 0 else f"{mv:+d}bp" + (f" to {lvl}" if lvl else ""),
                        "source": f"{row['source']} (wire report; official data pending)", "source_kind": "wire"}
    return out


HOURLY_MIN = 55   # news search and the Forex Factory calendar: at most about once an hour


def _due(state: dict, key: str, minutes: int) -> bool:
    last = state.get(key)
    return not last or (now_sgt() - dt.datetime.fromisoformat(last)).total_seconds() >= minutes * 60


def refresh(lookback_hours: int = 36, since: str | None = None):
    today = today_sgt()
    state = store.load_state()
    if state.get("probe_day") != today.isoformat():
        access_probe()
        state["probe_day"] = today.isoformat()
    hourly = bool(since) or _due(state, "hourly_last", HOURLY_MIN)
    # 1. Remarks: Telegram every run; news headlines about hourly.
    items = []
    try:
        items += telegram.collect(state, lookback_hours=lookback_hours, max_pages=max(120, lookback_hours * 2))
    except Exception as e:
        LOG.fail("TELEGRAM:collector", f"{type(e).__name__}: {e}")
    if since:   # backfill: two-week windows of headlines per bank
        d = dt.date.fromisoformat(since)
        while d < today:
            w = (d.isoformat(), min(today, d + dt.timedelta(days=14)).isoformat())
            for code in CFG["order"]:
                items += news.remarks(CFG["banks"][code]["news_name"], code, window=w)
            d += dt.timedelta(days=14)
    if hourly:
        for code in CFG["order"]:
            items += news.remarks(CFG["banks"][code]["news_name"], code, days=2)
    seen = set(state.get("seen_items", []))
    new = list({x["id"]: x for x in items if x["id"] not in seen}.values())
    state["seen_items"] = sorted(seen | {x["id"] for x in new})[-30000:]
    # Items queued for the former AI language step are handled once by the rules, then the queue is emptied.
    pend = inbox.load()
    cutoff = (today - dt.timedelta(days=3)).isoformat()
    recent = {rules.text_key(s["bank"], s.get("text") or "") for s in store.all_statements(cutoff[:7])
              if s.get("relevant") and s.get("bank") and s["ts"][:10] >= cutoff}
    rows = rules.headline_rows(pend["headlines"] + new, today.isoformat(), recent)
    # 2. Official speeches and statements.
    processed = set(state.get("processed_docs", []))
    docs = official_docs.collect(processed, since or (today - dt.timedelta(days=4)).isoformat())
    state["processed_docs"] = sorted(processed | {d["id"] for d in docs})[-8000:]
    rows += rules.document_rows(pend["documents"] + docs, today.isoformat())
    store.append_statements(rows)
    if pend["headlines"] or pend["documents"] or pend["expectations"]:
        inbox.save({"headlines": [], "documents": [], "expectations": []})
    # 3. Calendar, rates, releases; consensus from Forex Factory (about hourly).
    ex = store.load_expectations()
    recs = meetings.build(today=today, expectations=ex)
    if hourly:
        ff = consensus.forex_factory()
        ex = consensus.update(ex, recs, today, ff=ff)
        store.save_expectations(ex)
        consensus.archive_speeches(ff)
        state["hourly_last"] = now_sgt().isoformat(timespec="minutes")
    store.save_state(state)
    write_json(SNAPSHOT, recs, compact=True)
    # Decisions reported by two or more outlets, shown "per wires" until official data arrives.
    wire_from = (today - dt.timedelta(days=10)).isoformat()
    watch = rules.wire_decisions(recs, [s for s in store.all_statements(wire_from[:7]) if s["ts"][:10] >= wire_from],
                                 today.isoformat())
    meetings.annotate(recs, ex, watch, today)
    finish(recs, today, refreshed=True)
    check.run(recs, today)


def finish(recs: list[dict], today: dt.date, refreshed: bool = False):
    statements = store.all_statements()
    spec = spectrum.build(statements, today)
    health = store.update_health(LOG.as_dict())
    state = store.load_state()
    if refreshed:
        state["last_refresh"] = now_sgt().isoformat(timespec="minutes")
    store.save_state(state)
    build.write_site(recs, statements, spec, health, today, refreshed=state.get("last_refresh"))
    print(f"done: {len(recs)} calendar items, {sum(1 for s in statements if s.get('relevant'))} feed items, "
          f"failed sources: {sorted(k for k, v in LOG.as_dict().items() if not v['ok'])}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", metavar="YYYY-MM-DD")
    ap.add_argument("--lookback-hours", type=int, default=36)
    a = ap.parse_args()
    try:
        # Backfill: a week of Telegram (headline volume grows fast beyond that); news since the date.
        refresh(168 if a.backfill else a.lookback_hours, since=a.backfill)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
