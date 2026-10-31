"""Turns collected headlines and official documents into feed rows with plain
rules (no AI). Text is shown as published, with its source.

A headline is kept when it either
  * names a current committee member (seeds/members.json) and reads as
    something they said (a colon, or a verb such as 'says', 'warns'), or
  * reports a bank's own rate decision (bank name + 'holds/raises/cuts ...
    rate'), without forecast words ('expected', 'poll', ...).
Former officials, market-move lines and other central banks are dropped.
Remarks carry no hawkish/dovish judgement: stance is always neutral."""
from __future__ import annotations

import datetime as dt
import re

from .common import ROOT, now_sgt, read_json
from .spectrum import _norm, _tokens, active

ALIASES = {
    "FED": r"\b(?:Fed|FED|FOMC)\b|(?i:federal reserve)",
    "ECB": r"\bECB\b|(?i:european central bank)",
    "BOE": r"\b(?:BoE|BOE)\b|(?i:bank of england)",
    "BOJ": r"\b(?:BoJ|BOJ)\b|(?i:bank of japan|japan(?:.s|n|ese) central bank)",
    "BOK": r"\b(?:BoK|BOK)\b|(?i:bank of korea|(?:south )?korea(?:.s|n|ese) central bank)",
    "PBOC": r"\b(?:PBoC|PBOC|PBC)\b|(?i:people.s bank of china|china.s central bank)",
    "RBI": r"\bRBI\b|(?i:reserve bank of india|india(?:.s|n|ese) central bank)",
    "BNM": r"\bBNM\b|(?i:bank negara|malaysia(?:.s|n|ese) central bank)",
    "BI": r"\bBI\b|(?i:bank indonesia|indonesia(?:.s|n|ese) central bank)",
    "BOT": r"\b(?:BoT|BOT)\b|(?i:bank of thailand|thai central bank)",
    "HKMA": r"\bHKMA\b|(?i:hong kong monetary authority|hong kong)",
    "MAS": r"\bMAS\b|(?i:monetary authority of singapore)",
    "BSP": r"\bBSP\b|(?i:bangko sentral|philippines?(?:.s)? central bank)",
    "CBC": r"(?i:taiwan.s central bank|taiwan central bank|central bank of the republic of china)",
    "RBA": r"\bRBA\b|(?i:reserve bank of australia|australia(?:.s|n|ese) central bank)",
    "RBNZ": r"\bRBNZ\b|(?i:reserve bank of new zealand|new zealand.s central bank)",
}
# Surnames that are also ordinary words or very common names: kept only when
# the member's bank is named in the same headline.
COMMON = {
    "cook", "lane", "long", "baker", "mann", "pill", "taylor", "greene", "silk", "collins", "martin", "sing", "song",
    "wang", "yang", "kang", "ding", "chang", "liao", "chin", "chew", "shin", "hwang", "kumar", "singh", "gupta",
    "santos", "pereira", "hansen", "ross", "moulin", "logan", "daly", "barr", "bailey", "hauser", "kent", "jones",
    "hunter", "conway", "venable", "wilkinson", "gourley", "hewson", "jefferson", "powell", "waller", "schmid",
}
FIRST_NAMES = {
    "alan", "alberto", "alexander", "alvaro", "austan", "benjamin", "beth", "boris", "bruce", "carl", "carolyn", "catherine",
    "charl", "cheryl", "christine", "christopher", "clare", "dave", "emmanuel", "fabio", "frank", "frederick", "gabriel",
    "gaston", "isabel", "jeffrey", "jenny", "jerome", "jessica", "john", "karen", "kevin", "leon", "lisa", "lorie", "luis",
    "mary", "megan", "melinda", "michael", "michele", "michelle", "neel", "olaf", "olli", "omar", "paul", "peter", "piero",
    "pierre", "preston", "rebecca", "renee", "ricky", "romeo", "rosalia", "sarah", "susan", "swati", "walter", "yannis",
    "sanjay", "andrew", "anna", "philip", "thomas", "jose", "huw", "eli", "marnie", "hayley", "iain", "lian",
}
SPEECH = re.compile(r":|\b(?:says|said|sees?|warns?|signals?|flags?|tells?|urges?|notes?|stresses?|adds?|expects?|"
                    r"repeats?|reiterates?|believes?|thinks?|vows?|pledges?|rules? out|backs?|favou?rs?|calls? for|argues?|"
                    r"cautions?|predicts?|wants?|open to|in no hurry|not in a hurry|speaks?|comments?)\b", re.I)
DECISION = re.compile(r"\b(?:holds?|keeps?|leaves?|raises?|hikes?|cuts?|lowers?|reduces?|maintains?|unchanged|"
                      r"tightens?|eases?|steady)\b", re.I)
RATE_WORD = re.compile(r"\b(?:rates?|OCR|repo|policy|base rate|bank rate|S\$NEER|stance)\b", re.I)
# Words that mark a headline as a forecast, analysis or market story rather than the decision itself.
NOT_DECISION = re.compile(r"\b(?:expected|expects?|seen|sees|poll|economists?|analysts?|may|could|likely|bets?|traders?|"
                          r"forecasts?|preview|why|what|how|whether|ahead of|if|set to|chances?|odds|pressure|questions?|"
                          r"takeaways?|instant view|after|even as|sends?|swings?|markets?|stocks?|yields?|bonds?|treasury|"
                          r"dollar|yuan|yen|says?|believes?|should|would|can be|wants?|wall street|shares|equities|ends|"
                          r"rall(?:y|ies)|slides?|gains?|to (?:hold|keep|raise|hike|cut|lower|leave|hit|pause))\b|\?", re.I)
# "SOMEONE: ..." or "SOMEONE SAYS ..." -- the opening words say who is speaking.
PREFIX = re.compile(r"^([^:]{2,45}):|^(.{2,40}?)\s+(?:says?|said)\b", re.I)
# "..., SOMEONE says" -- the closing words say who is speaking.
SUFFIX = re.compile(r",\s*([^,]{2,40}?)\s+(?:says|said)\W*$", re.I)
# News about a member (succession, nomination, hearings) rather than something they said.
ABOUT = re.compile(r"\b(?:successor|replacement|nominat\w*|nominee|confirmation|hearing on)\b", re.I)
# A decision: the bank's name, at most two words, the decision verb, then the rate within a few words.
DECIDES = (r"\W*(?:[\w'’.-]+\W+){0,2}?(?:" + DECISION.pattern + r"|\b(?:left|kept|held|raised|hiked|lowered|pauses?|paused|puts?))" +
           r"\b.{0,40}?(?:\b(?:rates?|OCR|repo|policy|base rate|bank rate|S\$NEER)\b|steady|unchanged|on hold|fire)")
NOT_SPEAKER = re.compile(r"^(?:\*|breaking|update|urgent|flash|exclusive)\b", re.I)
# Features and comment pieces, not something an official said.
COMMENTARY = re.compile(r"^(?:analysis|explainer|opinion|column|factbox|commentary|editorial|instant view|podcast|video|live)\b", re.I)
DROP = re.compile(r"\b(?:former|ex-)|^(?:SPOT GOLD|GOLD|OIL|BRENT|WTI|US STOCKS|STOCKS|DOLLAR|TREASURY|YIELDS?)\b", re.I)
JUNK = re.compile(r"https?://\S+|#\w+|[\U0001F000-\U0001FAFF☀-➿️‍]")
MAX_CHARS = 320


def clean(text: str) -> str:
    t = re.sub(r"\s+", " ", JUNK.sub("", text or "")).strip(" -–—|")
    if len(t) > MAX_CHARS:
        t = t[:MAX_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + " …"
    return t


def _roster(today: str) -> dict[str, list[dict]]:
    r = read_json(ROOT / "seeds" / "members.json", {}) or {}
    return {b: [m for m in v.get("members", []) if active(m, today)] for b, v in r.items() if not b.startswith("_")}


def _keys(members: dict[str, list[dict]]) -> dict[str, tuple[str, dict, bool]]:
    """surname token -> (bank, member, distinctive). Tokens shared by two
    members, first names and short tokens are not keys."""
    seen: dict[str, list] = {}
    for bank, ms in members.items():
        for m in ms:
            for t in _tokens(m["name"]):
                seen.setdefault(t, []).append((bank, m))
    return {t: (v[0][0], v[0][1], t not in COMMON and len(t) >= 5)
            for t, v in seen.items() if len(v) == 1 and len(t) >= 4 and t not in FIRST_NAMES}


def banks_in(text: str) -> list[str]:
    """Banks named in the text, earliest mention first."""
    found = [(m.start(), b) for b, rx in ALIASES.items() if (m := re.search(rx, text))]
    return [b for _, b in sorted(found)]


def decision_bank(text: str) -> str | None:
    """The bank whose own decision the headline reports ('BOJ holds rates'), not
    one that is merely mentioned ('Fed officials make case for rate hikes')."""
    for bank in banks_in(text):
        for m in re.finditer(ALIASES[bank], text):
            if re.match(DECIDES, text[m.end():], re.I):
                return bank
    return None


def find_member(text: str, members: dict[str, list[dict]], keys: dict, only_bank: str | None = None,
                need_alias: bool = True) -> tuple[str, dict] | None:
    """Earliest member named in the text: full name first, then a surname key."""
    norm = f" {_norm(text)} "
    named = set(banks_in(text))
    hits = []
    for bank, ms in members.items():
        if only_bank and bank != only_bank:
            continue
        for m in ms:
            toks = _tokens(m["name"])
            if len(toks) > 1 and all(f" {t} " in norm for t in toks):
                hits.append((min(norm.find(f" {t} ") for t in toks), bank, m))
    for t, (bank, m, distinctive) in keys.items():
        if only_bank and bank != only_bank:
            continue
        pos = norm.find(f" {t} ")
        if pos >= 0 and (distinctive or bank in named or not need_alias):
            hits.append((pos, bank, m))
    if not hits:
        return None
    _, bank, m = min(hits, key=lambda h: h[0])
    return bank, m


def text_key(bank: str, text: str) -> tuple[str, str]:
    return bank, _norm(text).replace(" ", "")


def headline_rows(items: list[dict], today: str, recent: set | None = None) -> list[dict]:
    """recent: text_key()s already in the feed, so a headline repeated by a
    second outlet or a later post is shown once."""
    members = _roster(today)
    keys = _keys(members)
    rows, stamp, dup = [], now_sgt().isoformat(timespec="seconds"), set(recent or ())
    for it in sorted(items, key=lambda x: x["ts"]):
        text = clean(it.get("text", ""))
        if not text or DROP.search(text) or COMMENTARY.match(text):
            continue
        pre, suf = PREFIX.match(text), SUFFIX.search(text)
        who = [((pre[1] or pre[2]) if pre else "").strip(), (suf[1] if suf else "").strip()]
        # A closing "..., Ueda says" names the speaker on its own, so short surnames count there.
        if any(w and not NOT_SPEAKER.match(w) and not banks_in(w) and not find_member(w, members, keys, need_alias=(i == 0))
               for i, w in enumerate(who)):
            continue   # someone else speaking, e.g. "BESSENT: ... WARSH", "... on Fed's Cook delayed, Hassett says"
        hit = find_member(text, members, keys) if SPEECH.search(text) and not ABOUT.search(text) else None
        bank, speaker, role, kind = None, "", "", "remark"
        if hit:
            bank, m = hit
            speaker, role = m["name"], m.get("role") or ""
        elif not NOT_DECISION.search(text):
            bank = decision_bank(text)
            kind = "decision"
        key = text_key(bank, text) if bank else None
        if not bank or key in dup:
            continue
        dup.add(key)
        rows.append({"id": it["id"], "ts": it["ts"], "source": it["source"], "kind": it["kind"], "evidence": it["kind"],
                     "raw": it.get("text", ""), "url": it.get("url"), "relevant": True, "bank": bank,
                     "speaker": speaker, "role": role, "type": kind, "text": text, "stance": "neutral", "score": None,
                     "reason": "", "decision_bp": "", "decision_level": "", "classified": stamp, "model": "rules"})
    return rows


def document_rows(docs: list[dict], today: str) -> list[dict]:
    members = _roster(today)
    keys = _keys(members)
    rows, stamp = [], now_sgt().isoformat(timespec="seconds")
    for d in docs:
        if not d.get("date"):
            continue
        hit = find_member(f"{d['title']} {(d.get('text') or '')[:4000]}", members, keys, only_bank=d["bank"], need_alias=False)
        speaker, role = (hit[1]["name"], hit[1].get("role") or "") if hit else ("", "")
        rows.append({"id": d["id"], "ts": f"{d['date']}T12:00+08:00", "date_only": True, "source": "official", "kind": "official",
                     "evidence": "official", "url": d["url"], "title": d["title"], "lang": d.get("lang"), "relevant": True,
                     "bank": d["bank"], "speaker": speaker, "role": role, "type": "remark", "text": clean(d["title"]),
                     "stance": "neutral", "score": None, "reason": "", "classified": stamp, "model": "rules"})
    return rows


# Wire-reported decisions, used only until the bank's own data (or BIS) confirms.
HOLD = re.compile(r"\b(?:holds?|held|keeps?|kept|leaves?|left|maintains?|unchanged|steady|pauses?|paused|on hold)\b", re.I)
MOVE = re.compile(r"\b(raises?|raised|hikes?|hiked|lifts?|increases?|cuts?|lowers?|lowered|reduces?|reduced|trims?)\b"
                  r".{0,40}?\bby\s+(\d{2,3})\s*(?:bp|bps|basis[- ]points?)\b|\b(quarter|half)[- ]point\s+(hike|increase|rise|cut|reduction)", re.I)
AT_LEVEL = re.compile(r"\b(?:at|to)\s+(-?\d{1,2}(?:\.\d{1,2})?)\s*(?:%|per ?cent|percent)", re.I)
UP = re.compile(r"raise|hike|lift|increase|rise", re.I)


def wire_move(text: str) -> tuple[int, float | None] | None:
    """(move in bp, level after if stated) from a decision headline, or None."""
    lvl = AT_LEVEL.search(text)
    lvl = float(lvl[1]) if lvl else None
    m = MOVE.search(text)
    if m:
        bp = int(m[2]) if m[2] else (25 if m[3].lower() == "quarter" else 50)
        return (bp if UP.match(m[1] or m[4]) else -bp), lvl
    d = re.search(r"\b(raises?|raised|hikes?|hiked|lifts?|increases?|cuts?|lowers?|lowered|reduces?|reduced|trims?)\b", text, re.I)
    if d and lvl is not None:
        return ("up" if UP.match(d[1]) else "down"), lvl   # size worked out from the rate before
    if HOLD.search(text) and not re.search(r"\b(?:raises?|hikes?|cuts?|lowers?)\b", text, re.I):
        return 0, lvl
    return None


def wire_decisions(recs: list[dict], statements: list[dict], today: str) -> dict[str, dict]:
    """Decisions for past meetings that have no official decision yet, from
    decision headlines: at least two outlets must report the same move, and no
    outlet a different one. The label says 'per wires' until official data arrives."""
    out = {}
    for rec in recs:
        if rec["type"] != "meeting" or rec.get("decision_official") or rec["bank"] in ("MAS", "CBC") or rec["date"] > today:
            continue
        lo = (dt.date.fromisoformat(rec["date"]) - dt.timedelta(days=1)).isoformat()
        hi = (dt.date.fromisoformat(rec["date"]) + dt.timedelta(days=3)).isoformat()
        before = rec.get("rate_before")
        b = float(re.sub(r"[^\d.\-–]", "", before).split("–")[-1]) if before and re.search(r"\d", before) else None
        seen = {}
        for s in statements:
            if s.get("bank") == rec["bank"] and s.get("type") == "decision" and lo <= s["ts"][:10] <= hi:
                mv = wire_move(s.get("raw") or s.get("text") or "")
                if mv and isinstance(mv[0], str):   # "raises ... to 5.50%": the move is the level less the rate before
                    up = mv[0] == "up"
                    mv = (int(round((mv[1] - b) * 100)), mv[1]) if b is not None and (mv[1] > b) == up and mv[1] != b else None
                if mv:
                    seen.setdefault(mv[0], {}).setdefault(s["source"], (s.get("url"), mv[1]))
        if len(seen) != 1:
            continue
        move, srcs = next(iter(seen.items()))
        if len(srcs) < 2:
            continue
        stated = {v[1] for v in srcs.values() if v[1] is not None}
        level = (b + move / 100) if b is not None else (stated.pop() if len(stated) == 1 else None)
        if b is not None and stated and any(abs(x - level) > 1e-9 for x in stated):
            continue   # an outlet's stated level disagrees with the rate before plus the move
        lv = f"{level:.2f}%" if level is not None and "–" not in (before or "") else None
        label = ("Hold" + (f" at {lv}" if lv else "") if move == 0 else f"{move:+d}bp" + (f" to {lv}" if lv else "")) + " (per wires)"
        out[rec["id"]] = {"move_bp": move, "label": label, "level": lv, "source": next(iter(srcs.values()))[0],
                          "source_kind": "wires", "sources": sorted(srcs)}
    return out
