"""Headlines from reputable outlets via Google News search feeds. Only the
headline, outlet and date are used (no article text), and only outlets on the
allowlist below. Used for (a) remarks by officials of banks whose own sites
cannot be read automatically and (b) polls/consensus before meetings."""
from __future__ import annotations

import datetime as dt
import email.utils
import html as htmllib
import re
import urllib.parse

from .common import SGT, fetch, sha, FetchError

ALLOW = {
    "reuters", "bloomberg", "bloomberg.com", "financial times", "the wall street journal", "wsj", "cnbc", "marketwatch",
    "barron's", "associated press", "ap news", "afp", "nikkei asia", "the japan times", "kyodo news", "nhk world-japan",
    "yonhap news agency", "the korea herald", "the korea times", "korea joongang daily", "the business times", "the straits times",
    "cna", "bernama", "the edge malaysia", "nst online", "the star", "malay mail", "the malaysian reserve", "the jakarta post",
    "antara news", "jakarta globe", "bangkok post", "the nation thailand", "thai pbs world", "inquirer.net", "philstar.com",
    "businessworld", "businessmirror", "gma news online", "rappler", "focus taiwan", "taipei times", "the economic times",
    "mint", "livemint", "business standard", "moneycontrol", "the hindu", "businessline", "the hindu businessline",
    "hindustan times", "south china morning post", "caixin global", "xinhua", "yicai global", "china daily", "vietnam news",
    "vnexpress international", "tuoi tre news", "theinvestor", "the investor", "vietnamplus", "australian financial review",
    "abc news", "the sydney morning herald", "the guardian", "rnz", "nz herald", "interest.co.nz", "stuff", "bbc",
    "investinglive", "fxstreet", "mni", "morningstar", "the edge singapore", "edgeprop", "nasdaq", "fortune", "axios",
    "investing.com", "euronews", "politico", "the national", "reuters.com",
}


def _feed(query: str, source_id: str) -> list[dict]:
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query)
           + "&hl=en-SG&gl=SG&ceid=SG:en")
    raw = fetch(url, source_id, pause=1.0)
    out = []
    for title, link, pub, src in re.findall(r"<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>.*?<pubDate>(.*?)</pubDate>.*?<source[^>]*>(.*?)</source>", raw, re.S):
        outlet = htmllib.unescape(src).strip()
        if outlet.lower() not in ALLOW:
            continue
        t = htmllib.unescape(title)
        t = re.sub(r"\s+-\s+" + re.escape(outlet) + r"\s*$", "", t).strip()
        when = dt.datetime(*email.utils.parsedate(pub)[:6], tzinfo=dt.timezone.utc).astimezone(SGT)
        out.append({"id": "nw-" + sha(outlet + t), "ts": when.isoformat(timespec="minutes"), "text": t,
                    "source": outlet, "kind": "news", "url": htmllib.unescape(link).strip()})
    return out


def remarks(bank_name: str, bank: str, days: int = 2, window: tuple[str, str] | None = None) -> list[dict]:
    """Headlines likely to report officials' remarks or decisions."""
    q = f'"{bank_name}" (governor OR said OR says OR signals OR warns OR decision OR holds OR raises OR cuts)'
    q += f" after:{window[0]} before:{window[1]}" if window else f" when:{days}d"
    try:
        items = _feed(q, f"NEWS:{bank}")
    except FetchError:
        return []
    for x in items:
        x["bank_hint"] = bank
    return items


def polls(bank_name: str, bank: str, days: int = 21, window: tuple[str, str] | None = None) -> list[str]:
    """Dated headline lines about expectations for an upcoming decision."""
    q = f'"{bank_name}" (poll OR economists OR expected OR forecast OR "seen") (rate OR rates)'
    q += f" after:{window[0]} before:{window[1]}" if window else f" when:{days}d"
    try:
        items = _feed(q, f"NEWS-POLLS:{bank}")
    except FetchError:
        return []
    return [f"{x['ts'][:10]} | {x['source']} | {x['text']}" for x in sorted(items, key=lambda x: x["ts"], reverse=True)]
