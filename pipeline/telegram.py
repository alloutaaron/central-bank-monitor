"""Reads the public web preview of Telegram channels (t.me/s/<channel>), the
same page anyone can open without an account. Pages backwards ~20 posts at a
time until it reaches the last post seen, then keeps only posts that mention a
covered central bank or a committee member."""
from __future__ import annotations

import datetime as dt
import html as htmllib
import re

from .common import ROOT, SGT, fetch, read_json, FetchError

CHANNELS = {"firstsquaw": "First Squawk", "WalterBloomberg": "Walter Bloomberg"}

_POST = re.compile(r'data-post="[^/"]+/(\d+)"(.*?)(?=data-post="|$)', re.S)
_TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
_TIME = re.compile(r'<time datetime="([^"]+)"')


def _clean(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>", " ", fragment)
    t = re.sub(r"<[^>]+>", "", t)
    t = htmllib.unescape(t)
    t = re.sub(r"\(\s*@\w+\s*\)", "", t)          # channel self-tags like "( @FirstSquaw )"
    return re.sub(r"\s+", " ", t).strip()


def parse_page(raw: str) -> list[dict]:
    out = []
    for pid, body in _POST.findall(raw):
        tm, tx = _TIME.search(body), _TEXT.search(body)
        if not (tm and tx):
            continue
        when = dt.datetime.fromisoformat(tm.group(1)).astimezone(SGT)
        text = _clean(tx.group(1))
        if text:
            out.append({"id": int(pid), "dt": when, "text": text})
    return out


def _matcher():
    """Regex of bank aliases and member surnames (from the verified rosters)."""
    cfg = read_json(ROOT / "config" / "banks.json", {})["banks"]
    mem = read_json(ROOT / "seeds" / "members.json", {})
    terms = {a for b in cfg.values() for a in b["aliases"]}
    for b in mem.values():
        if isinstance(b, dict):
            for m in b.get("members", []):
                last = m["name"].replace("Jr.", "").split()[-1] if m["name"].isascii() else None
                if last and len(last) > 3:
                    terms.add(last.upper())
    terms |= {"CENTRAL BANK", "RATE DECISION", "POLICY RATE", "LOAN PRIME RATE", "LPR"}
    terms -= {"MAS"}  # too ambiguous on its own; "MONETARY AUTHORITY OF SINGAPORE" remains
    return re.compile(r"\b(" + "|".join(sorted(map(re.escape, terms), key=len, reverse=True)) + r")\b", re.I)


def fetch_channel(channel: str, after_id: int | None, not_before: dt.datetime, max_pages: int = 120) -> list[dict]:
    posts, before = {}, None
    for _ in range(max_pages):
        url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
        try:
            page = parse_page(fetch(url, f"TELEGRAM:{channel}", pause=1.2))
        except FetchError:
            break
        if not page:
            break
        for p in page:
            posts[p["id"]] = p
        oldest = min(page, key=lambda p: p["id"])
        if (after_id and oldest["id"] <= after_id) or oldest["dt"] < not_before:
            break
        before = oldest["id"]
    return sorted((p for p in posts.values() if (not after_id or p["id"] > after_id) and p["dt"] >= not_before),
                  key=lambda p: p["id"])


def collect(state: dict, lookback_hours: int = 36, max_pages: int = 120) -> list[dict]:
    """New central-bank-related posts from all channels since the last run."""
    rx = _matcher()
    not_before = dt.datetime.now(SGT) - dt.timedelta(hours=lookback_hours)
    seen = state.setdefault("telegram_last_id", {})
    out = []
    for ch, label in CHANNELS.items():
        posts = fetch_channel(ch, seen.get(ch), not_before, max_pages=max_pages)
        if posts:
            seen[ch] = max(p["id"] for p in posts)
        for p in posts:
            if rx.search(p["text"]):
                out.append({"id": f"tg-{ch}-{p['id']}", "ts": p["dt"].isoformat(timespec="minutes"),
                            "text": p["text"][:400], "source": label, "kind": "telegram",
                            "url": f"https://t.me/{ch}/{p['id']}"})
    return out
