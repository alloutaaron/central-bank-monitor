"""Turns schedules + rate histories + expectations into meeting records:
current rate going in, expected decision (with its basis), actual decision
(with its source), and whether the outcome matched expectations."""
from __future__ import annotations

import datetime as dt
import re
from bisect import bisect_right

from . import rates, schedules
from .common import ROOT, read_json, to_sgt, today_sgt, LOG, FetchError

CFG = read_json(ROOT / "config" / "banks.json", {})


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


class Path_:
    """Policy-rate path from a list of changes (date -> level after)."""

    def __init__(self, changes: list[dict], last_obs: str | None = None):
        self.c = sorted(changes, key=lambda x: x["date"])
        self.dates = [x["date"] for x in self.c]
        self.last_obs = last_obs or (self.c[-1]["date"] if self.c else None)

    def on(self, day: str) -> dict | None:
        i = bisect_right(self.dates, day)
        return self.c[i - 1] if i else None

    def change_within(self, start: str, end: str) -> dict | None:
        for x in self.c:
            if start <= x["date"] <= end:
                return x
        return None


def _bp(a: dict | None, b: dict | None) -> int | None:
    if not a or not b or a.get("mid") is None or b.get("mid") is None:
        return None
    return int(round((b["mid"] - a["mid"]) * 100))


def _fmt_level(bank: str, x: dict | None) -> str | None:
    if not x:
        return None
    lv = x.get("level")
    if lv is None:
        return None
    return f"{lv}%" if "-" not in str(lv) else f"{lv.replace('-', '–')}%"


def build_paths() -> dict[str, Path_]:
    """Best available path per bank: official structured source, then
    hand-verified seeds, then BIS. Each change keeps its source."""
    paths = {}
    yesterday = (today_sgt() - dt.timedelta(days=1)).isoformat()
    for bank, fn in rates.OFFICIAL.items():
        try:
            ch = fn()
            if ch:
                # Change-only tables (Fed, ECB, BoE, BoK) read today are current
                # through yesterday, so an unchanged rate after a past meeting is a
                # hold. Tables with one row per meeting (BNM, BI, BoT) record holds.
                last = yesterday if bank in ("FED", "ECB", "BOE", "BOK") else ch[-1]["date"]
                paths[bank] = Path_(ch, last)
        except FetchError:
            pass
        except Exception as e:
            LOG.fail(f"{bank}:rate-parser", f"{type(e).__name__}: {e}")
    for bank in ("RBA", "RBNZ", "BSP", "RBI"):
        if bank in paths:      # official table read successfully (e.g. RBA): seeds not needed
            continue
        seed = [dict(x, mid=float(x["level"]), kind="decision") for x in rates.seeded(bank)]
        try:
            bis, last = rates.bis_changes(bank)
        except FetchError:
            bis, last = [], None
        merged = {x["date"]: x for x in bis}
        for x in seed:   # seeds are decision dates; drop BIS effective-date duplicates within 3 days
            for d in list(merged):
                if 0 <= (_d(d) - _d(x["date"])).days <= 3 and abs(merged[d]["mid"] - x["mid"]) < 1e-9:
                    merged.pop(d)
            merged[x["date"]] = x
        if merged:
            paths[bank] = Path_(list(merged.values()), max(last or "", max(merged)))
    # BoJ and HKMA: their own decision statements; BIS for the level before
    # the first statement read, and as the fallback if the bank's site fails.
    for bank, fn in (("BOJ", rates.boj), ("HKMA", rates.hkma)):
        try:
            off = fn()
        except FetchError:
            off = []
        except Exception as e:
            LOG.fail(f"{bank}:rate-parser", f"{type(e).__name__}: {e}")
            off = []
        try:
            bis, last = rates.bis_changes(bank)
            first = rates.bis_series().get(rates.BIS_AREAS[bank], [])
            if first:
                bis = [{"date": first[0][0], "mid": first[0][1], "level": rates._fmt(first[0][1]), "kind": "effective", "src": "BIS WS_CBPOL"}] + bis
        except FetchError:
            bis, last = [], None
        if off:
            # BoJ statements are one per meeting (holds included); HKMA issues a
            # release only when the Base Rate changes, so no release means unchanged.
            older = [x for x in bis if x["date"] < off[0]["date"]]
            paths[bank] = Path_(older + off, off[-1]["date"] if bank == "BOJ" else today_sgt().isoformat())
        elif bis:
            paths[bank] = Path_(bis, last)
    # PBoC: 7-day reverse repo rate (BIS still reports the 1Y LPR for China).
    ch, last = rates.pboc_7d()
    if ch:
        paths["PBOC"] = Path_(ch, last)
    # BI's official page lists only the last ten meetings: extend with BIS.
    if "BI" in paths:
        try:
            bis, _ = rates.bis_changes("BI")
            older = [x for x in bis if x["date"] < paths["BI"].c[0]["date"]]
            paths["BI"] = Path_(older + paths["BI"].c, paths["BI"].last_obs)
        except FetchError:
            pass
    return paths


LAG_DAYS = {"FED": 2, "ECB": 7, "BOJ": 7, "HKMA": 2, "PBOC": 2}


def _seed_initial(paths: dict[str, Path_]):
    """Ensure each path has a level before the first change in the window."""
    try:
        series = rates.bis_series()
    except FetchError:
        return
    for bank, p in paths.items():
        area = rates.BIS_AREAS.get(bank)
        if not area or not series.get(area) or not p.c:
            continue
        d0, v0 = series[area][0]
        if p.c[0]["date"] > d0:
            p.c.insert(0, {"date": d0, "mid": v0, "level": rates._fmt(v0), "kind": "effective", "src": "BIS WS_CBPOL"})
            p.dates.insert(0, d0)


def decision_for(bank: str, date: str, path: Path_ | None, extra: dict) -> tuple[dict | None, dict | None]:
    """(rate_before, decision) for a meeting on `date` (local)."""
    if path is None:
        return None, None
    day_before = (_d(date) - dt.timedelta(days=1)).isoformat()
    before = path.on(day_before)
    lag = LAG_DAYS.get(bank, 0)
    end = (_d(date) + dt.timedelta(days=lag)).isoformat()
    after = path.change_within(date, end) or path.on(date)
    known = path.last_obs and path.last_obs >= date
    if bank in ("FED", "ECB", "BOJ", "HKMA") and not path.change_within(date, end):
        known = path.last_obs and path.last_obs >= end
    if not known:
        return before, None
    move = _bp(before, after)
    if move is None:
        return before, None
    lvl = _fmt_level(bank, after)
    label = "Hold" + (f" at {lvl}" if lvl else "") if move == 0 else f"{move:+d}bp to {lvl}"
    return before, {"move_bp": move, "label": label, "level": lvl, "source": after.get("src") if move else (after or {}).get("src"),
                    "source_kind": "official" if "BIS" not in str((after or {}).get("src")) else "BIS"}


def mas_record(entry: dict) -> dict:
    parts = []
    for k, name in (("slope", "slope"), ("width", "width"), ("centre", "centre")):
        if entry.get(k):
            parts.append(f"{name}: {entry[k][0].lower()}{entry[k][1:]}" if k != "centre" else entry[k])
    move = "Unchanged" if not parts else "; ".join(parts)
    sign = 0 if not parts else (1 if any("increase" in p.lower() or "upward" in p.lower() for p in parts) else -1)
    return {"move_bp": sign, "label": ("S$NEER " + move) if parts else "Unchanged S$NEER policy band",
            "source": entry["src"], "source_kind": "official"}


def build(today: dt.date | None = None, expectations: dict | None = None, watch: dict | None = None,
          start: str = "2025-01-01", end: str = "2027-12-31") -> list[dict]:
    today = today or today_sgt()
    expectations = expectations or {}
    watch = watch or {}
    sched = schedules.collect()
    paths = build_paths()
    _seed_initial(paths)
    mas_hist = {}
    try:
        mas_hist = {x["date"]: x for x in rates.mas()}
    except FetchError:
        pass
    cbc_rates = {}
    for e in sched.get("CBC", []):
        for x in rates.cbc([e]):
            cbc_rates[x["date"]] = x
    recs = []
    for bank in CFG["order"]:
        meta = CFG["banks"][bank]
        for m in sched.get(bank, []):
            if not (start <= m["date"] <= end):
                continue
            mid = f"{bank}-{m['date']}"
            rec = {"id": mid, "bank": bank, "date": m["date"], "type": "meeting", "days": m.get("days"),
                   "flags": [f for f in m.get("flags", []) if f not in ("Press conference",)],
                   "time_sgt": to_sgt(_d(m["date"]), meta.get("decision_time"), meta["tz"]),
                   "time_note": meta.get("time_note"), "schedule_src": m.get("src"), "note": m.get("note")}
            if bank == "MAS":
                h = mas_hist.get(m["date"])
                rec["rate_before"] = "S$NEER policy band"
                rec["decision"] = mas_record(h) if h else None
            elif bank == "CBC":
                h = cbc_rates.get(m["date"])
                prev = max((v for k, v in cbc_rates.items() if k < m["date"]), key=lambda v: v["date"], default=None)
                rec["rate_before"] = f"{prev['level']}%" if prev else None
                if h:
                    mv = int(round((h["mid"] - prev["mid"]) * 100)) if prev else 0
                    rec["decision"] = {"move_bp": mv, "label": ("Hold at " if mv == 0 else f"{mv:+d}bp to ") + f"{h['level']}%",
                                       "source": h["src"], "source_kind": "official"}
                else:
                    rec["decision"] = None
            else:
                before, dec = decision_for(bank, m["date"], paths.get(bank), {})
                rec["rate_before"] = _fmt_level(bank, before)
                rec["decision"] = dec
            rec["decision_official"] = rec.get("decision")
            recs.append(rec)
    recs += lpr_events(start, end, today)
    recs += rate_change_events("HKMA", paths.get("HKMA"), start)
    recs += rate_change_events("PBOC", paths.get("PBOC"), start)
    attach_releases(recs, sched)
    return annotate(recs, expectations, watch, today)


def annotate(recs: list[dict], expectations: dict, watch: dict, today: dt.date) -> list[dict]:
    """Apply expectations and wire-reported decisions (when official data has not
    caught up), then status and whether the outcome matched expectations. Run
    again after the language step without re-fetching anything."""
    for rec in recs:
        if rec["type"] != "meeting":
            continue
        dec = rec.get("decision_official") or watch.get(rec["id"])
        rec["decision"] = dec
        ex = expectations.get(rec["id"])
        rec["expected"] = ex
        rec["status"] = "done" if dec else ("awaiting" if _d(rec["date"]) <= today else "scheduled")
        rec["matched"] = None
        if dec and ex and dec.get("move_bp") is not None:
            sgn = lambda v: (v > 0) - (v < 0)
            exp_dir = ex.get("dir", sgn(ex["move_bp"]) if ex.get("move_bp") is not None else None)
            if rec["bank"] == "MAS" or ex.get("move_bp") is None:
                # direction only (MAS band moves; polls that give no size)
                rec["matched"] = None if exp_dir is None else exp_dir == sgn(dec["move_bp"])
            else:
                rec["matched"] = int(ex["move_bp"]) == int(dec["move_bp"])
    return recs


def attach_releases(recs: list[dict], sched: dict):
    """Link each meeting to its statement, press conference, minutes and reports,
    and list releases that come out on a later day as their own calendar items."""
    from . import releases
    rel = releases.collect(sched)
    by_meeting: dict[tuple, list] = {}
    for r in rel:
        if r.get("meeting"):
            by_meeting.setdefault((r["bank"], r["meeting"]), []).append(r)
    for rec in recs:
        if rec["type"] == "meeting":
            rec["links"] = sorted(by_meeting.get((rec["bank"], rec["date"]), []), key=lambda r: (r.get("date") or "9", r["kind"]))
        elif rec["type"] == "rate-change" and rec["bank"] == "HKMA":
            rec["links"] = [r for r in rel if r["bank"] == "HKMA" and r.get("date") == rec["date"]]
    later = [r for r in rel if r["kind"] in ("minutes", "account", "sop", "report", "highlights", "record")
             and r.get("date") and r.get("meeting") and r["date"] != r["meeting"]]
    for r in later:
        recs.append({"id": f"{r['bank']}-{r['kind']}-{r['date']}", "bank": r["bank"], "type": "release", "date": r["date"],
                     "status": "done" if r["status"] == "published" else "scheduled", "title": r["title"],
                     "meeting": r["meeting"], "url": r.get("url"), "basis": r.get("basis"), "decision": None,
                     "expected": None, "matched": None, "time_sgt": None})


def lpr_events(start: str, end: str, today: dt.date) -> list[dict]:
    """Monthly LPR fixings: official history for the past, the PBoC rule for the future."""
    out = []
    try:
        hist = schedules.lpr_history(max(_d(start), dt.date(2024, 12, 1)), today)
    except FetchError:
        hist = []
    prev = None
    for h in hist:
        if prev and h["date"] >= start:
            d1, d5 = int(round((h["1Y"] - prev["1Y"]) * 100)), int(round((h["5Y"] - prev["5Y"]) * 100))
            label = "Unchanged" if d1 == d5 == 0 else f"1Y {d1:+d}bp, 5Y {d5:+d}bp"
            out.append({"id": f"PBOC-LPR-{h['date']}", "bank": "PBOC", "date": h["date"], "type": "lpr",
                        "time_sgt": to_sgt(_d(h["date"]), "09:00", "Asia/Shanghai"), "status": "done",
                        "rate_before": f"1Y {prev['1Y']:.2f}% / 5Y {prev['5Y']:.2f}%",
                        "decision": {"move_bp": d1, "label": f"{label}: 1Y {h['1Y']:.2f}%, 5Y {h['5Y']:.2f}%",
                                     "source": "https://www.chinamoney.com.cn/chinese/bklpr/", "source_kind": "official"},
                        "expected": None, "matched": None})
        prev = h
    last = hist[-1]["date"] if hist else start
    for e in schedules.lpr_dates(today, _d(end)):
        if e["date"] > last:
            out.append({"id": f"PBOC-LPR-{e['date']}", "bank": "PBOC", "date": e["date"], "type": "lpr",
                        "time_sgt": to_sgt(_d(e["date"]), "09:00", "Asia/Shanghai"), "status": "scheduled",
                        "date_note": "Date per PBoC rule (20th; moved for holidays)",
                        "rate_before": f"1Y {hist[-1]['1Y']:.2f}% / 5Y {hist[-1]['5Y']:.2f}%" if hist else None,
                        "decision": None, "expected": None, "matched": None})
    return out


RATE_CHANGE_NAME = {"HKMA": "Base Rate", "PBOC": "7-day reverse repo"}


def rate_change_events(bank: str, path: Path_ | None, start: str) -> list[dict]:
    """Banks that move their rate without scheduled meetings (HKMA, and the
    PBoC's 7-day reverse repo): show each change on the day it applied."""
    if not path:
        return []
    out, prev = [], None
    for x in path.c:
        if prev and x["date"] >= start:
            mv = int(round((x["mid"] - prev["mid"]) * 100))
            kind = "BIS" if "BIS" in str(x["src"]) else "official" if re.search(r"pbc\.gov\.cn|hkma\.gov\.hk", str(x["src"])) else "wire"
            out.append({"id": f"{bank}-{x['date']}", "bank": bank, "date": x["date"], "type": "rate-change",
                        "status": "done", "rate_before": f"{prev['level']}%", "time_sgt": None,
                        "decision": {"move_bp": mv, "label": f"{RATE_CHANGE_NAME[bank]} {mv:+d}bp to {x['level']}%",
                                     "level": f"{x['level']}%", "source": x["src"], "source_kind": kind},
                        "expected": None, "matched": None})
        prev = x
    return out
