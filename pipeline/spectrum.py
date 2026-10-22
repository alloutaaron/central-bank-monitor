"""Places each verified committee member on the hawk/dove spectrum from the
scored statements (methodology/hawk_dove_rubric.md): weighted mean of scores,
60-day half-life, 365-day window, evidence-type weights."""
from __future__ import annotations

import datetime as dt
import math
import re
import unicodedata

from .common import ROOT, read_json

HALF_LIFE = 60.0
WINDOW = 365
WEIGHT = {"vote": 2.0, "official": 1.0, "news": 0.75, "telegram": 0.75}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", " ", s)


def _tokens(name: str) -> set[str]:
    return {t for t in _norm(name).split() if len(t) > 1 and t not in {"jr", "dr", "mr", "ms", "sir", "dato", "datuk", "sri"}}


def match_member(speaker: str, members: list[dict]) -> dict | None:
    """Match a speaker string to a roster entry: surname match, then
    disambiguate by the other name tokens."""
    if not speaker:
        return None
    sp = _tokens(speaker)
    if not sp:
        # non-Latin names (e.g. Taiwan directors listed in Chinese)
        return next((m for m in members if m["name"] and m["name"] in speaker), None)
    cands = []
    for m in members:
        mt = _tokens(m["name"])
        if not mt:
            continue
        overlap = len(sp & mt)
        if overlap:
            cands.append((overlap, m))
    if not cands:
        return None
    cands.sort(key=lambda x: -x[0])
    if len(cands) > 1 and cands[0][0] == cands[1][0]:
        return None  # ambiguous (e.g. two Bhattacharyas) -> do not guess
    return cands[0][1]


def active(m: dict, today: str) -> bool:
    return (not m.get("from") or m["from"] <= today) and (not m.get("until") or m["until"] >= today)


def build(statements: list[dict], today: dt.date) -> dict:
    roster = read_json(ROOT / "seeds" / "members.json", {})
    order = read_json(ROOT / "config" / "banks.json", {})["order"]
    tday = today.isoformat()
    out = {}
    for bank in order:
        info = roster.get(bank, {})
        members = [m for m in info.get("members", []) if active(m, tday)]
        acc = {m["name"]: [0.0, 0.0, 0, None] for m in members}   # sum w*s, sum w, n, last date
        for s in statements:
            if s.get("bank") != bank or not s.get("relevant") or s.get("score") is None:
                continue
            age = (today - dt.date.fromisoformat(s["ts"][:10])).days
            if age < 0 or age > WINDOW:
                continue
            m = match_member(s.get("speaker", ""), members)
            if not m:
                continue
            w = WEIGHT.get(s.get("evidence", s.get("kind", "news")), 0.75) * math.pow(0.5, age / HALF_LIFE)
            a = acc[m["name"]]
            a[0] += w * s["score"]; a[1] += w; a[2] += 1
            a[3] = max(a[3] or "", s["ts"][:10])
        placed, unplaced = [], []
        for m in members:
            sw, w, n, last = acc[m["name"]]
            entry = {"name": m["name"], "role": m.get("role"), "chair": bool(m.get("chair")),
                     "voter": m.get("voter"), "secondary": bool(m.get("secondary"))}
            if n and w > 0:
                entry.update(position=round(sw / w, 3), n=n, last=last,
                             weight=round(w, 3))
                placed.append(entry)
            else:
                unplaced.append(entry)
        out[bank] = {"committee": info.get("committee"), "note": info.get("note"), "verified": info.get("verified"),
                     "placed": sorted(placed, key=lambda e: e["position"]), "unplaced": unplaced}
    return out
