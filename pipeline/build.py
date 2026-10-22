"""Writes the public data files the page reads (docs/data): only what the page
displays (no scores or rubric text). Official links and source links are
included so items can be opened."""
from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict

from .common import ROOT, SGT, now_sgt, read_json, write_json

OUT = ROOT / "docs" / "data"
CFG = read_json(ROOT / "config" / "banks.json", {})
TITLE = {"FED": "FOMC", "ECB": "Governing Council", "BOE": "MPC", "BOJ": "Policy Board", "BOK": "Monetary Policy Board",
         "PBOC": "LPR fixing", "RBI": "MPC", "BNM": "MPC", "BI": "Board of Governors", "BOT": "MPC", "SBV": "Policy",
         "HKMA": "Base Rate", "MAS": "Monetary Policy Statement", "BSP": "Monetary Board", "CBC": "Board meeting",
         "RBA": "Monetary Policy Board", "RBNZ": "MPC"}
# Sources whose official sites refuse automated access: data comes from the
# fallbacks named here, and the page says so.
ACCESS_NOTES = {
    "RBNZ": "rbnz.govt.nz blocks automated access: decisions verified by hand, then BIS and wire reports; schedule verified by hand",
    "BSP": "Decisions verified by hand from BSP press releases; new decisions from wire reports and BIS until confirmed; schedule verified by hand",
    "BNM": "bnm.gov.my speech pages block automated access: remarks from news headlines; decisions from BNM's official API",
    "RBA": "Schedule verified by hand; rates from rba.gov.au when readable, otherwise hand-verified records and BIS",
}


def _sgt_date(rec: dict) -> str:
    return rec["time_sgt"][:10] if rec.get("time_sgt") else rec["date"]


def _event(rec: dict) -> dict:
    ev = {"id": rec["id"], "bank": rec["bank"], "type": rec["type"], "date": _sgt_date(rec), "local_date": rec["date"],
          "time": rec["time_sgt"][11:16] if rec.get("time_sgt") else None, "title": TITLE.get(rec["bank"], "Meeting"),
          "status": rec["status"], "rate_before": rec.get("rate_before"), "flags": rec.get("flags") or [],
          "note": rec.get("note") or rec.get("date_note") or rec.get("time_note"), "days": rec.get("days")}
    if rec["type"] == "rate-change":
        ev["title"] = "Base Rate change"
    if rec["type"] == "release":
        ev.update(title=rec["title"], url=rec.get("url"), meeting=rec.get("meeting"), basis=rec.get("basis"))
    if rec.get("links"):
        ev["links"] = [{"title": r["title"], "url": r.get("url"), "date": r.get("date"), "status": r["status"],
                        "basis": r.get("basis")} for r in rec["links"]]
    d = rec.get("decision")
    if d:
        ev["decision"] = {"label": d["label"], "move": d.get("move_bp"), "src": d.get("source_kind")}
    e = rec.get("expected")
    if e:
        ev["expected"] = {"label": e["label"], "move": e.get("move_bp"), "dir": e.get("dir"), "basis": e.get("basis")}
    ev["matched"] = rec.get("matched")
    return ev


def _tok(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9.%]+", s.lower()))


def feed_items(statements: list[dict]) -> list[dict]:
    rows = [s for s in statements if s.get("relevant") and s.get("bank") not in (None, "NONE") and s.get("text")]
    rows.sort(key=lambda s: s["ts"])
    kept: list[dict] = []
    for s in rows:
        t = _tok(s["text"])
        dup = False
        for k in kept[-60:]:
            if k["bank"] == s["bank"] and (k.get("speaker") or "") == (s.get("speaker") or ""):
                gap = abs((dt.datetime.fromisoformat(s["ts"]) - dt.datetime.fromisoformat(k["ts"])).total_seconds())
                kt = _tok(k["text"])
                if gap < 6 * 3600 and len(t & kt) / max(1, len(t | kt)) >= 0.45:
                    dup = True
                    break
        if not dup:
            kept.append(s)
    out = []
    for s in kept:
        ts = dt.datetime.fromisoformat(s["ts"]).astimezone(SGT)
        src = "Official" if s.get("kind") == "official" else s.get("source") or ""
        out.append({"id": s["id"], "ts": ts.isoformat(timespec="minutes"), "date_only": bool(s.get("date_only")),
                    "bank": s["bank"], "speaker": s.get("speaker") or "", "role": s.get("role") or "",
                    "text": s["text"], "stance": s.get("stance") or "neutral", "url": s.get("url"), "src": src,
                    "kind": "decision" if s.get("type") == "decision" else ("official" if s.get("kind") == "official" else "remark")})
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out


def current_rates(recs: list[dict], today: str) -> dict:
    cur = {}
    for r in sorted(recs, key=lambda r: r["date"]):
        if r["date"] > today:
            continue
        d = r.get("decision")
        if d and r["bank"] != "MAS":
            lvl = d.get("level") or re.search(r"(?:to|at) (.+)$", d["label"]) and re.search(r"(?:to|at) (.+)$", d["label"]).group(1)
            if r["type"] == "lpr":
                lvl = d["label"].split(": ", 1)[-1]
            if lvl:
                cur[r["bank"]] = {"level": lvl, "as_of": r["date"], "src": d.get("source_kind")}
        elif r.get("rate_before") and r["bank"] not in cur and r["bank"] != "MAS":
            cur[r["bank"]] = {"level": r["rate_before"], "as_of": r["date"], "src": "official"}
    for r in recs:  # banks with no decision yet in range: use the rate going into the next meeting
        if r["bank"] not in cur and r.get("rate_before") and r["bank"] != "MAS":
            cur[r["bank"]] = {"level": r["rate_before"], "as_of": r["date"], "src": "official"}
    # MAS targets the S$NEER band: describe the latest change and the latest decision.
    mas = [r for r in recs if r["bank"] == "MAS" and r.get("decision") and r["date"] <= today]
    if mas:
        last = max(mas, key=lambda r: r["date"])
        moved = [r for r in mas if r["decision"]["move_bp"] != 0]
        lab = moved[-1]["decision"]["label"].split(" (")[0].lower() if moved else ""
        detail = (f"{lab} ({moved[-1]['date'][8:10]}/{moved[-1]['date'][5:7]}/{moved[-1]['date'][2:4]})" if moved else "No recent change")
        cur["MAS"] = {"level": "S$NEER band", "detail": detail, "as_of": last["date"], "src": "official"}
    return cur


def stale_list(health: dict) -> list[dict]:
    out = []
    for sid, h in sorted(health.items()):
        if not h.get("ok"):
            out.append({"source": sid, "last_ok": h.get("last_ok"), "error": (h.get("error") or "")[:160]})
    return out


def write_site(recs, statements, spec, health, today: dt.date, ai: dict):
    tday = today.isoformat()
    order = CFG["order"]
    # Calendar: meetings/LPR/HKMA changes + scheduled speeches + past official speeches.
    cal = defaultdict(list)
    for r in recs:
        ev = _event(r)
        cal[ev["date"][:7]].append(ev)
    for sp in read_json(ROOT / "data" / "scheduled_speeches.json", []) or []:
        cal[sp["ts"][:7]].append({"id": f"sp-{sp['bank']}-{sp['ts']}", "bank": sp["bank"], "type": "speech", "date": sp["ts"][:10],
                                  "time": sp["ts"][11:16], "title": sp["title"], "status": "done" if sp["ts"][:10] < tday else "scheduled"})
    for s in statements:
        if s.get("kind") == "official" and s.get("relevant") and s.get("bank") not in (None, "NONE"):
            cal[s["ts"][:7]].append({"id": f"sp-{s['id']}", "bank": s["bank"], "type": "speech", "date": s["ts"][:10], "time": None,
                                     "title": (s.get("speaker") or "Official") + (" – " + s["title"][:80] if s.get("title") else ""),
                                     "status": "done", "stance": s.get("stance")})
    months_cal = sorted(cal)
    for mth, evs in cal.items():
        evs.sort(key=lambda e: (e["date"], e.get("time") or "99:99", order.index(e["bank"]) if e["bank"] in order else 99))
        write_json(OUT / "calendar" / f"{mth}.json", {"month": mth, "events": evs}, compact=True)
    # Feed by month.
    feed = feed_items(statements)
    by_m = defaultdict(list)
    for f in feed:
        by_m[f["ts"][:7]].append(f)
    for mth, items in by_m.items():
        write_json(OUT / "feed" / f"{mth}.json", {"month": mth, "items": items}, compact=True)
    # Banks.
    cur = current_rates(recs, tday)
    nxt, last = {}, {}
    for r in sorted(recs, key=lambda r: r["date"]):
        if r["type"] in ("meeting", "lpr") and r["date"] >= tday and r["bank"] not in nxt and r["status"] != "done":
            e = r.get("expected") or {}
            nxt[r["bank"]] = {"date": _sgt_date(r), "time": r["time_sgt"][11:16] if r.get("time_sgt") else None,
                              "title": TITLE.get(r["bank"]), "expected": e.get("label"), "expected_move": e.get("move_bp"), "expected_dir": e.get("dir"),
                              "basis": e.get("basis")}
        if r["type"] in ("meeting", "lpr", "rate-change") and r.get("decision") and r["date"] <= tday:
            last[r["bank"]] = {"date": r["date"], "move": r["decision"].get("move_bp"), "label": r["decision"]["label"],
                               "src": r["decision"].get("source_kind")}
    tbc = (read_json(ROOT / "seeds" / "meetings.json", {}) or {}).get("_tbc", {})
    banks = []
    for code in order:
        b = CFG["banks"][code]
        banks.append({"code": code, "name": b["name"], "short": b["short"], "country": b["country"], "rate_label": b["rate_label"],
                      "rate": cur.get(code), "last": last.get(code), "next": nxt.get(code), "next_note": tbc.get(code),
                      "access_note": ACCESS_NOTES.get(code)})
    # Spectrum: positions only (no scores, no reasons).
    spec_out = {}
    for code, s in spec.items():
        spec_out[code] = {"committee": s["committee"], "note": s["note"], "verified": s["verified"],
                          "placed": [{k: v for k, v in m.items() if k in ("name", "role", "chair", "voter", "position", "n", "last", "secondary")}
                                     for m in s["placed"]],
                          "unplaced": [{k: v for k, v in m.items() if k in ("name", "role", "chair", "voter", "secondary")} for m in s["unplaced"]]}
    write_json(OUT / "spectrum.json", spec_out, compact=True)
    write_json(OUT / "banks.json", {"order": order, "banks": banks}, compact=True)
    write_json(OUT / "meta.json", {
        "updated": now_sgt().isoformat(timespec="minutes"), "today": tday,
        "months": {"calendar": months_cal, "feed": sorted(by_m)},
        "stale": stale_list(health), "language": {"last_run": ai.get("last_run"), "pending": ai.get("pending")},
    }, compact=True)
