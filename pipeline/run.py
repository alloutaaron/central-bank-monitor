"""Morning collection job. Usage:
    python -m pipeline.run                       # daily
    python -m pipeline.run --backfill 2026-04-01 # also queue history since that date
Collects every source, builds the calendar and rates, and queues text for the
language step in data/inbox/pending.json. The language step is the Claude
routine (ROUTINE.md), or the Claude API when ANTHROPIC_API_KEY is set. Never
aborts on one failed source: failures are recorded and shown as stale."""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import traceback

from . import consensus, inbox, llm, meetings, news, official_docs, spectrum, store, telegram, build
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


def expectation_tasks(recs: list[dict], today: dt.date, ex: dict, state: dict, backlog: int) -> list[dict]:
    """Poll headlines for upcoming meetings (next 21 days) and, a few a day, for
    past meetings that have no recorded expectation yet."""
    tasks, none = [], set(state.get("expect_none", []))
    for r in recs:
        if r["type"] != "meeting" or r["bank"] == "HKMA":
            continue
        d = dt.date.fromisoformat(r["date"])
        name = CFG["banks"][r["bank"]]["news_name"]
        if today <= d <= today + dt.timedelta(days=21) and not (ex.get(r["id"]) or {}).get("frozen"):
            # Only headlines dated before the meeting day: same-day ones may report the decision itself.
            lines = [l for l in news.polls(name, r["bank"], days=21) if l[:10] < r["date"]]
            if lines:
                tasks.append({"id": r["id"], "bank": r["bank"], "date": r["date"], "rate_before": r.get("rate_before"),
                              "as_of": today.isoformat(), "headlines": lines[:40]})
    past = [r for r in recs if r["type"] == "meeting" and r["bank"] != "HKMA" and r["id"] not in ex and r["id"] not in none
            and "2025-01-01" <= r["date"] < today.isoformat()]
    for r in sorted(past, key=lambda r: r["date"], reverse=True)[:backlog]:
        d = dt.date.fromisoformat(r["date"])
        win = ((d - dt.timedelta(days=14)).isoformat(), d.isoformat())
        lines = [l for l in news.polls(CFG["banks"][r["bank"]]["news_name"], r["bank"], window=win) if l[:10] < r["date"]]
        if lines:
            tasks.append({"id": r["id"], "bank": r["bank"], "date": r["date"], "rate_before": r.get("rate_before"),
                          "as_of": win[1], "headlines": lines[:40]})
        else:
            state.setdefault("expect_none", []).append(r["id"])
    return tasks


def api_language_step(pend: dict):
    """Optional: when ANTHROPIC_API_KEY is set, do the language step here and
    write the same outbox format the routine writes."""
    if not llm.available() or not (pend["headlines"] or pend["documents"] or pend["expectations"]):
        return
    out = {"headlines": [], "documents": [], "expectations": []}
    res = llm.classify_headlines([{"id": x["id"], "ts": x["ts"][:16].replace("T", " "), "text": x["text"]} for x in pend["headlines"]]) or []
    out["headlines"] = res
    for d in pend["documents"]:
        r = llm.process_document(d["bank"], d["title"], d["date"], d["lang"], d["text"])
        if r:
            out["documents"].append(dict(r, id=d["id"]))
    for t in pend["expectations"]:
        r = llm.extract_expectation(t["bank"], t["date"], t.get("rate_before") or "unknown", t["headlines"])
        if r:
            out["expectations"].append(dict(r, id=t["id"]))
    write_json(inbox.OUTBOX / f"{now_sgt().strftime('%Y%m%d-%H%M')}-api.json", out)


def daily(lookback_hours: int = 36, backlog: int = 25, since: str | None = None):
    today = today_sgt()
    state = store.load_state()
    access_probe()
    pend = inbox.load()
    # 1. Remarks: Telegram + reputable-news headlines.
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
    for code in CFG["order"]:
        items += news.remarks(CFG["banks"][code]["news_name"], code, days=2)
    seen = set(state.get("seen_items", []))
    new = list({x["id"]: x for x in items if x["id"] not in seen}.values())
    inbox.add_headlines(pend, new)
    state["seen_items"] = sorted(seen | {x["id"] for x in new})[-30000:]
    # 2. Official speeches and statements (original language).
    processed = set(state.get("processed_docs", []))
    docs = official_docs.collect(processed, since or (today - dt.timedelta(days=4)).isoformat())
    inbox.add_documents(pend, docs)
    state["processed_docs"] = sorted(processed | {d["id"] for d in docs})[-8000:]
    # 3. Calendar, rates, releases; deterministic consensus (Forex Factory).
    ex = store.load_expectations()
    recs = meetings.build(today=today, expectations=ex)
    ff = consensus.forex_factory()
    ex = consensus.update(ex, recs, today, ff=ff)
    store.save_expectations(ex)
    consensus.archive_speeches(ff)
    inbox.set_expectation_tasks(pend, expectation_tasks(recs, today, ex, state, backlog))
    inbox.save(pend)
    store.save_state(state)
    write_json(SNAPSHOT, recs, compact=True)
    # 4. Language step via the API if a key is set; otherwise the routine picks up the inbox.
    api_language_step(pend)
    if llm.available():
        from .finalize import apply_outbox
        apply_outbox()
    watch = decision_watch(store.all_statements((today - dt.timedelta(days=4)).isoformat()[:7]), recs, today)
    meetings.annotate(recs, store.load_expectations(), watch, today)
    return finish(recs, today, refreshed=True)


def finish(recs: list[dict], today: dt.date, language_step: bool = False, refreshed: bool = False):
    statements = store.all_statements()
    spec = spectrum.build(statements, today)
    health = store.update_health(LOG.as_dict())
    state = store.load_state()
    if language_step or llm.available():
        state["language_last_run"] = now_sgt().isoformat(timespec="minutes")
    if refreshed:   # the full source refresh, as opposed to a page rebuild after the language step
        state["last_refresh"] = now_sgt().isoformat(timespec="minutes")
    store.save_state(state)
    pend = inbox.load()
    lang = {"last_run": state.get("language_last_run"), "pending": len(pend["headlines"]) + len(pend["documents"]) + len(pend["expectations"])}
    build.write_site(recs, statements, spec, health, today, ai=lang, refreshed=state.get("last_refresh"))
    print(f"done: {len(recs)} calendar items, {sum(1 for s in statements if s.get('relevant'))} feed items, "
          f"pending for language step: {lang['pending']}, failed sources: "
          f"{sorted(k for k, v in LOG.as_dict().items() if not v['ok'])}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", metavar="YYYY-MM-DD")
    ap.add_argument("--lookback-hours", type=int, default=36)
    ap.add_argument("--expect-backlog", type=int, default=25)
    a = ap.parse_args()
    try:
        # Backfill: a week of Telegram (headline volume grows fast beyond that); news since the date.
        daily(168 if a.backfill else a.lookback_hours, a.expect_backlog, since=a.backfill)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
