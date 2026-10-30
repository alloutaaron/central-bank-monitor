"""Official speeches, press conferences and statements, read from each bank's
own feed or listing page, in English. Returns new documents with their text
(used for the date when the listing has none, and to identify the speaker)."""
from __future__ import annotations

import datetime as dt
import email.utils
import html as htmllib
import io
import re

from .common import fetch, html_to_text, sha, FetchError, LOG

# kind=rss: RSS feed. kind=list: listing page + link regex; date from the link
# (group 'date', formats below) or from the document page.
SOURCES = [
    {"bank": "FED", "kind": "rss", "url": "https://www.federalreserve.gov/feeds/speeches.xml", "lang": "en"},
    {"bank": "FED", "kind": "rss", "url": "https://www.federalreserve.gov/feeds/testimony.xml", "lang": "en"},
    {"bank": "ECB", "kind": "rss", "url": "https://www.ecb.europa.eu/rss/press.html", "lang": "en",
     "keep": r"/press/(key|inter|press_conference)/"},
    {"bank": "BOE", "kind": "rss", "url": "https://www.bankofengland.co.uk/rss/speeches", "lang": "en"},
    {"bank": "HKMA", "kind": "rss", "url": "https://www.hkma.gov.hk/eng/other-information/rss/rss_speeches.xml", "lang": "en"},
    {"bank": "RBA", "kind": "rss", "url": "https://www.rba.gov.au/rss/rss-cb-speeches.xml", "lang": "en"},
    # BoJ, PBoC and CBC: English pages (no translation step), which can appear later than the original.
    {"bank": "BOJ", "kind": "list", "url": "https://www.boj.or.jp/en/about/press/index.htm", "lang": "en", "base": "https://www.boj.or.jp",
     "link": r"/en/about/press/(?:koen|kaiken)_\d{4}/k[ok](?P<date>\d{6})[a-z]\.(?:htm|pdf)"},
    {"bank": "PBOC", "kind": "list", "url": "https://www.pbc.gov.cn/en/3688110/3688175/index.html", "lang": "en",
     "base": "https://www.pbc.gov.cn", "link": r"/en/3688110/3688175/(?P<date>\d{8})\d+/index\.html"},
    {"bank": "BNM", "kind": "list", "url": "https://www.bnm.gov.my/speeches-interviews", "lang": "en", "base": "",
     "link": r"https://www\.bnm\.gov\.my/-/[a-z0-9-]+", "title_keep": r"(?i)speech|address|remarks|keynote|interview|statement"},
    {"bank": "CBC", "kind": "list", "url": "https://www.cbc.gov.tw/en/lp-448-2.html", "lang": "en", "base": "https://www.cbc.gov.tw",
     "link": r"/en/cp-448-\d+-[0-9a-fA-F]+-2\.html", "title_keep": r"(?i)governor|monetary policy|policy rate|interest rate|exchange rate|board|press conference"},
]


def _date_from_token(tok: str) -> str | None:
    try:
        if len(tok) == 6:   # YYMMDD
            return dt.date(2000 + int(tok[:2]), int(tok[2:4]), int(tok[4:])).isoformat()
        if len(tok) == 8:   # YYYYMMDD
            return dt.date(int(tok[:4]), int(tok[4:6]), int(tok[6:])).isoformat()
    except ValueError:
        return None
    return None


def _date_from_text(text: str, day_first: bool = False) -> str | None:
    if day_first:   # Vietnamese pages: 21/10/2026
        m = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b", text)
        if m:
            try:
                return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
            except ValueError:
                pass
    m = re.search(r"(\d{1,2}) (January|February|March|April|May|June|July|August|September|October|November|December) (20\d\d)", text)
    if m:
        return dt.datetime.strptime(" ".join(m.groups()), "%d %B %Y").date().isoformat()
    m = re.search(r"(20\d\d)[-./年](\d{1,2})[-./月](\d{1,2})", text)
    if m:
        return dt.date(*map(int, m.groups())).isoformat()
    m = re.search(r"(1\d\d)[年/.](\d{1,2})[月/.](\d{1,2})", text)  # ROC calendar (Taiwan): 115 = 2026
    if m:
        return dt.date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))).isoformat()
    return None


def list_items(src: dict) -> list[dict]:
    sid = f"{src['bank']}:official-{src['kind']}"
    raw = fetch(src["url"], sid)
    out = []
    if src["kind"] == "rss":
        for blk in re.findall(r"<item\b.*?</item>", raw, re.S):
            title = re.search(r"<title>(.*?)</title>", blk, re.S)
            link = re.search(r"<link>(.*?)</link>", blk, re.S)
            pub = re.search(r"<pubDate>(.*?)</pubDate>", blk, re.S)
            dcd = re.search(r"<dc:date>(\d{4}-\d{2}-\d{2})", blk)
            if not (title and link):
                continue
            url = htmllib.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", link.group(1))).strip()
            if src.get("keep") and not re.search(src["keep"], url):
                continue
            t = htmllib.unescape(re.sub(r"<!\[CDATA\[|\]\]>|<[^>]+>", "", title.group(1))).strip()
            date = dcd.group(1) if dcd else None
            if pub and not date:
                p = email.utils.parsedate(pub.group(1))
                date = dt.date(*p[:3]).isoformat() if p else None
            out.append({"bank": src["bank"], "title": t, "url": url, "date": date, "lang": src["lang"]})
    else:
        for href, inner in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', raw, re.S):
            m = re.search(src["link"], href)
            if not m:
                continue
            t = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", inner))).strip()
            if len(t) < 6 or (src.get("title_keep") and not re.search(src["title_keep"], t)):
                continue
            url = href if href.startswith("http") else src["base"] + href
            date = _date_from_token(m.group("date")) if "date" in m.groupdict() and m.group("date") else None
            if not date and src.get("date_in_title"):
                dm = re.search(src["date_in_title"], t)       # e.g. SBV "(19/10/2026)" = day/month/year
                if dm:
                    date = dt.date(int(dm.group(3)), int(dm.group(2)), int(dm.group(1))).isoformat()
                    t = t[:dm.start()].strip()
            out.append({"bank": src["bank"], "title": t, "url": url, "date": date, "lang": src["lang"]})
    seen, res = set(), []
    for x in out:
        if x["url"] not in seen:
            seen.add(x["url"]); x["id"] = "doc-" + sha(x["url"]); res.append(x)
    return res


def document_text(item: dict) -> str:
    sid = f"{item['bank']}:official-doc"
    if item["url"].lower().endswith(".pdf"):
        from pypdf import PdfReader
        data = fetch(item["url"], sid, binary=True, timeout=25)
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages[:25])
    return html_to_text(fetch(item["url"], sid, timeout=25))


def collect(processed: set[str], since: str, max_docs_per_source: int = 25) -> list[dict]:
    """New official documents dated on/after `since`, with text attached.
    Per-source cap and short timeouts keep one slow site from stalling the run."""
    import time as _time
    out = []
    for src in SOURCES:
        fetched = 0
        try:
            items = list_items(src)
        except FetchError:
            continue
        except Exception as e:
            LOG.fail(f"{src['bank']}:official-{src['kind']}", f"parser error: {type(e).__name__}: {e}")
            continue
        started = _time.time()
        for it in items:
            if it["id"] in processed:
                continue
            if it["date"] and it["date"] < since:   # dated from the feed/link: skip without downloading
                processed.add(it["id"])
                continue
            if fetched >= max_docs_per_source or _time.time() - started > 240:
                if fetched:   # reachable, just a backlog: progress, not a failure
                    LOG.ok(f"{src['bank']}:official-doc", "backlog: remaining documents next run")
                else:
                    LOG.fail(f"{src['bank']}:official-doc", "no document downloaded within the time budget")
                break
            fetched += 1
            try:
                text = document_text(it)
            except FetchError:
                continue
            except Exception as e:
                LOG.fail(f"{it['bank']}:official-doc", f"{type(e).__name__}: {e}")
                continue
            it["date"] = it["date"] or _date_from_text(text[:3000], day_first=it["lang"] == "vi")
            if not it["date"] or it["date"] < since:
                processed.add(it["id"])
                continue
            it["text"] = text
            out.append(it)
    return out
