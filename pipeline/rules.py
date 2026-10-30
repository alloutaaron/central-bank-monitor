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

import re

from .common import ROOT, now_sgt, read_json
from .spectrum import _norm, _tokens, active

ALIASES = {
    "FED": r"\b(?:Fed|FED|FOMC)\b|(?i:federal reserve)",
    "ECB": r"\bECB\b|(?i:european central bank)",
    "BOE": r"\b(?:BoE|BOE)\b|(?i:bank of england)",
    "BOJ": r"\b(?:BoJ|BOJ)\b|(?i:bank of japan)",
    "BOK": r"\b(?:BoK|BOK)\b|(?i:bank of korea)",
    "PBOC": r"\b(?:PBoC|PBOC|PBC)\b|(?i:people.s bank of china|china.s central bank)",
    "RBI": r"\bRBI\b|(?i:reserve bank of india)",
    "BNM": r"\bBNM\b|(?i:bank negara)",
    "BI": r"\bBI\b|(?i:bank indonesia)",
    "BOT": r"\b(?:BoT|BOT)\b|(?i:bank of thailand|thai central bank)",
    "HKMA": r"\bHKMA\b|(?i:hong kong monetary authority|hong kong)",
    "MAS": r"\bMAS\b|(?i:monetary authority of singapore)",
    "BSP": r"\bBSP\b|(?i:bangko sentral)",
    "CBC": r"(?i:taiwan.s central bank|taiwan central bank|central bank of the republic of china)",
    "RBA": r"\bRBA\b|(?i:reserve bank of australia)",
    "RBNZ": r"\bRBNZ\b|(?i:reserve bank of new zealand)",
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
                          r"rall(?:y|ies)|slides?|gains?|to (?:hold|keep|raise|hike|cut|lower|leave))\b|\?", re.I)
# "SOMEONE: ..." or "SOMEONE SAYS ..." -- the opening words say who is speaking.
PREFIX = re.compile(r"^([^:]{2,45}):|^(.{2,40}?)\s+(?:says?|said)\b", re.I)
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
        pre = PREFIX.match(text)
        who = (pre[1] or pre[2]).strip() if pre else ""
        if who and not NOT_SPEAKER.match(who) and not banks_in(who) and not find_member(who, members, keys):
            continue   # someone else speaking, e.g. "BESSENT: ... CONFIDENCE IN WARSH", "EU'S COSTA SAYS ... LAGARDE"
        hit = find_member(text, members, keys) if SPEECH.search(text) else None
        bank, speaker, role, kind = None, "", "", "remark"
        if hit:
            bank, m = hit
            speaker, role = m["name"], m.get("role") or ""
        else:
            named = banks_in(text)
            if named and DECISION.search(text) and RATE_WORD.search(text) and not NOT_DECISION.search(text):
                bank, kind = named[0], "decision"
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
