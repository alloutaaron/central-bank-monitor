"""Official policy releases with links: decision statements, press conferences,
minutes (or the bank's equivalent) and policy reports.

Each parser returns release dicts:
  {"bank", "kind": statement|pressconf|minutes|account|sop|record|highlights|report,
   "meeting": local decision date it belongs to (or None), "date": release date
   (local), "url": official link or None, "status": published|scheduled,
   "basis": where a future date comes from (published calendar or stated rule)}
Future dates are included only where the bank publishes them or states a rule
on its own site (the rule is quoted in 'basis')."""
from __future__ import annotations

import datetime as dt
import html as htmllib
import re

from .common import fetch, html_to_text, month_num, LOG, FetchError

MONTHS = r"(January|February|March|April|May|June|July|August|September|October|November|December)"
KIND_LABEL = {"statement": "Statement", "pressconf": "Press conference", "minutes": "Minutes", "account": "Account",
              "sop": "Summary of Opinions", "record": "Record of meeting", "highlights": "Meeting highlights",
              "report": "Policy report", "communique": "Committee communiqué"}


def _d8(s: str) -> str:
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8])).isoformat()


def _d6(s: str) -> str:
    return dt.date(2000 + int(s[:2]), int(s[2:4]), int(s[4:6])).isoformat()


def _plus(day: str, n: int) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=n)).isoformat()


def _rel(bank, kind, meeting, date, url, status="published", basis=None, title=None):
    return {"bank": bank, "kind": kind, "meeting": meeting, "date": date, "url": url, "status": status,
            "basis": basis, "title": title or KIND_LABEL.get(kind, kind)}


def fed(meetings: list[str]) -> list[dict]:
    base = "https://www.federalreserve.gov"
    raw = fetch(base + "/monetarypolicy/fomccalendars.htm", "FED:calendar")
    out = []
    for m in re.finditer(r'href="(/newsevents/pressreleases/monetary(\d{8})a\.htm)"', raw):
        out.append(_rel("FED", "statement", _d8(m.group(2)), _d8(m.group(2)), base + m.group(1)))
    for m in re.finditer(r'href="(/monetarypolicy/fomcpresconf(\d{8})\.htm)"', raw):
        out.append(_rel("FED", "pressconf", _d8(m.group(2)), _d8(m.group(2)), base + m.group(1)))
    for m in re.finditer(r'href="(/monetarypolicy/fomcprojtabl(\d{8})\.htm)"', raw):
        out.append(_rel("FED", "report", _d8(m.group(2)), _d8(m.group(2)), base + m.group(1), title="Summary of Economic Projections"))
    published = set()
    for m in re.finditer(r'href="(/monetarypolicy/fomcminutes(\d{8})\.htm)"', raw):
        rel = re.search(r"\(Released " + MONTHS + r" (\d{1,2}), (\d{4})\)", raw[m.end():m.end() + 600])
        day = (dt.date(int(rel.group(3)), month_num(rel.group(1)), int(rel.group(2))).isoformat() if rel else None)
        meet = _d8(m.group(2))
        published.add(meet)
        out.append(_rel("FED", "minutes", meet, day or meet, base + m.group(1)))
    # The calendar page states that minutes are released three weeks after the decision.
    for meet in meetings:
        if meet not in published:
            out.append(_rel("FED", "minutes", meet, _plus(meet, 21), None, "scheduled",
                            "Fed: minutes are released three weeks after the policy decision"))
    return out


def ecb() -> list[dict]:
    out = []
    for y in range(2025, dt.date.today().year + 1):
        base = "https://www.ecb.europa.eu"
        try:
            acc = fetch(f"{base}/press/accounts/{y}/html/index_include.en.html", "ECB:accounts")
            for m in re.finditer(r'href="(/press/accounts/\d{4}/html/ecb\.mg(\d{6})[^"]+\.en\.html)"[^>]*>\s*Meeting of ([^<]+)<', acc):
                md = re.search(r"(\d{1,2}) " + MONTHS + r" (\d{4})", m.group(3))
                meet = dt.date(int(md.group(3)), month_num(md.group(2)), int(md.group(1))).isoformat() if md else None
                out.append(_rel("ECB", "account", meet, _d6(m.group(2)), base + m.group(1)))
            st = fetch(f"{base}/press/press_conference/monetary-policy-statement/{y}/html/index_include.en.html", "ECB:statements")
            for m in re.finditer(r'href="(/press/press_conference/monetary-policy-statement/\d{4}/html/ecb\.is(\d{6})[^"]+\.en\.html)"', st):
                out.append(_rel("ECB", "pressconf", _d6(m.group(2)), _d6(m.group(2)), base + m.group(1), title="Press conference statement"))
            dec = fetch(f"{base}/press/govcdec/mopo/{y}/html/index_include.en.html", "ECB:decisions-archive")
            for m in re.finditer(r'href="(/press/pr/date/\d{4}/html/ecb\.mp(\d{6})[^"]+\.en\.html)"', dec):
                out.append(_rel("ECB", "statement", _d6(m.group(2)), _d6(m.group(2)), base + m.group(1), title="Monetary policy decisions"))
        except FetchError:
            continue
    return out


def boe(meetings: list[dict]) -> list[dict]:
    """Summary and minutes are published with each decision; the Monetary Policy
    Report with the quarterly ones (both shown on the MPC dates page)."""
    out = []
    for m in meetings:
        d = dt.date.fromisoformat(m["date"])
        slug = f"{d.strftime('%B').lower()}-{d.year}"
        st = "published" if m["date"] <= dt.date.today().isoformat() else "scheduled"
        out.append(_rel("BOE", "minutes", m["date"], m["date"], f"https://www.bankofengland.co.uk/monetary-policy-summary-and-minutes/{d.year}/{slug}",
                        st, "BoE: summary and minutes are published with the decision", title="Summary and minutes"))
        if "MPR" in (m.get("flags") or []):
            out.append(_rel("BOE", "report", m["date"], m["date"], f"https://www.bankofengland.co.uk/monetary-policy-report/{d.year}/{slug}",
                            st, "BoE MPC dates page", title="Monetary Policy Report"))
    return out


def boj() -> list[dict]:
    """The MPM schedule table lists, per meeting: statement, Outlook Report,
    Summary of Opinions and minutes, with release dates (links once out)."""
    out = []
    base = "https://www.boj.or.jp"
    for url, sid in ((base + "/en/mopo/mpmsche_minu/index.htm", "BOJ:mpm-schedule"), (base + "/en/mopo/mpmsche_minu/past.htm", "BOJ:mpm-schedule-past")):
        try:
            raw = fetch(url, sid)
        except FetchError:
            continue
        for ym in re.finditer(r'id="p(\d{4})"(.*?)(?=id="p\d{4}"|$)', raw, re.S):
            year = int(ym.group(1))
            if year < 2025:
                continue
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", ym.group(2), re.S):
                cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
                if len(cells) < 4:
                    continue
                txt = [re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", c))).strip() for c in cells]
                md = re.search(r"(Jan|Feb|Mar|Apr|May|June?|July?|Aug|Sept?|Oct|Nov|Dec)\.?\s+\d{1,2}\s*\(\w+\.?\),\s*(?:(Jan|Feb|Mar|Apr|May|June?|July?|Aug|Sept?|Oct|Nov|Dec)\.?\s+)?(\d{1,2})", txt[0])
                if not md:
                    continue
                meet = dt.date(year, month_num(md.group(2) or md.group(1)), int(md.group(3))).isoformat()

                def date_of(t):
                    x = re.search(r"(Jan|Feb|Mar|Apr|May|June?|July?|Aug|Sept?|Oct|Nov|Dec)\.?\s+(\d{1,2})\s*\(", t)
                    if not x:
                        return None
                    mo = month_num(x.group(1))
                    yy = year + 1 if mo < dt.date.fromisoformat(meet).month - 6 else year
                    return dt.date(yy, mo, int(x.group(2))).isoformat()

                def link(c, pat):
                    x = re.search(r'href="([^"]*' + pat + r'[^"]*)"', c)
                    return (base + x.group(1)) if x and x.group(1).startswith("/") else (x.group(1) if x else None)

                st_link = link(cells[0], r"/mpmdeci/")
                out.append(_rel("BOJ", "statement", meet, meet, st_link, "published" if st_link else "scheduled", "BoJ MPM schedule"))
                for idx, kind, pat in ((1, "report", r"/outlook|/gaiyo|/mpmdeci"), (2, "sop", r"/opinion_"), (3, "minutes", r"/minu_")):
                    if idx >= len(cells):
                        continue
                    d = date_of(txt[idx])
                    if not d:
                        continue
                    u = link(cells[idx], pat)
                    out.append(_rel("BOJ", kind, meet, d, u, "published" if u else "scheduled", "BoJ MPM schedule",
                                    title="Outlook Report" if kind == "report" else None))
    return out


def bot() -> list[dict]:
    """Schedule rows: decision, press release, minutes (two weeks later, as the
    page states), Monetary Policy Report, Monetary Policy Forum slides."""
    url = "https://www.bot.or.th/en/our-roles/monetary-policy/mpc-meeting.html"
    raw = fetch(url, "BOT:mpc-schedule").replace("\\r\\n", " ").replace('\\"', '"')
    base = "https://www.bot.or.th"
    out = []
    for sec in re.finditer(r"Schedule (\d{4})(.*?)(?=Schedule \d{4}|$)", raw, re.S):
        if int(sec.group(1)) < 2025:
            continue
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", sec.group(2), re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            if len(cells) < 4:
                continue
            txt = [re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", c))).strip() for c in cells]

            def d_of(t):
                x = re.search(r"(\d{1,2})\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*(\d{4})", t)
                return dt.date(int(x.group(3)), month_num(x.group(2)), int(x.group(1))).isoformat() if x else None

            def link(c):
                x = re.search(r'href="([^"]+)"', c)
                return (base + x.group(1) if x.group(1).startswith("/") else x.group(1)) if x else None

            meet = d_of(txt[1]) if len(txt) > 1 else None
            if not meet:
                continue
            if len(cells) > 2:
                u = link(cells[2])
                out.append(_rel("BOT", "statement", meet, meet, u, "published" if u else "scheduled", "BoT MPC schedule", title="Press release"))
            if len(cells) > 3:
                u = link(cells[3])
                out.append(_rel("BOT", "minutes", meet, d_of(txt[3]) or _plus(meet, 14), u, "published" if u else "scheduled",
                                "BoT: minutes are published 2 weeks after the meeting"))
            if len(cells) > 4 and (d_of(txt[4]) or link(cells[4])):
                u = link(cells[4])
                out.append(_rel("BOT", "report", meet, d_of(txt[4]) or meet, u, "published" if u else "scheduled",
                                "BoT MPC schedule", title="Monetary Policy Report"))
    return out


def rba() -> list[dict]:
    url = "https://www.rba.gov.au/statistics/cash-rate/"
    raw = fetch(url, "RBA:cash-rate")
    out = []
    for m in re.finditer(r'href="(/media-releases/\d{4}/mr-\d{2}-\d+\.html)"[^>]*>\s*Statement\s*</a>.*?href="(/monetary-policy/rba-board-minutes/\d{4}/(\d{4}-\d{2}-\d{2})\.html)"', raw, re.S):
        meet = m.group(3)
        out.append(_rel("RBA", "statement", meet, meet, "https://www.rba.gov.au" + m.group(1), title="Statement"))
        out.append(_rel("RBA", "minutes", meet, None, "https://www.rba.gov.au" + m.group(2)))
    return out


def rbi() -> list[dict]:
    url = "https://www.rbi.org.in/Scripts/AnnualPolicy.aspx"
    raw = fetch(url, "RBI:policy-page")
    out = []
    for h, t in re.findall(r'<a[^>]+href="([^"]*prid=\d+)"[^>]*>(.*?)</a>', raw, re.S):
        t = re.sub(r"<[^>]+>|\s+", " ", htmllib.unescape(t)).strip()
        mm = re.search(MONTHS + r" (\d{1,2})(?: to |-)(\d{1,2}), (\d{4})", t)
        if not mm:
            continue
        meet = dt.date(int(mm.group(4)), month_num(mm.group(1)), int(mm.group(3))).isoformat()
        link = h if h.startswith("http") else "https://www.rbi.org.in/Scripts/" + h.split("/")[-1]
        if t.lower().startswith("minutes"):
            out.append(_rel("RBI", "minutes", meet, _plus(meet, 14), link))
        elif re.search(r"(?i)resolution|statement", t):
            out.append(_rel("RBI", "statement", meet, meet, link, title="MPC resolution"))
    return out


def bnm(meetings: list[str]) -> list[dict]:
    today = dt.date.today().isoformat()
    return [_rel("BNM", "statement", d, d, f"https://www.bnm.gov.my/-/monetary-policy-statement-{d[8:10]}{d[5:7]}{d[:4]}",
                 "published" if d <= today else "scheduled", "BNM MPC schedule", title="Monetary Policy Statement") for d in meetings]


def bi() -> list[dict]:
    url = "https://www.bi.go.id/en/statistik/indikator/bi-rate.aspx"
    raw = fetch(url, "BI:bi-rate")
    out = []
    for m in re.finditer(r"(\d{1,2}) " + MONTHS + r" (20\d\d)\s*</td>.*?href=\"([^\"]*news-release[^\"]+)\"", raw, re.S):
        d = dt.date(int(m.group(3)), month_num(m.group(2)), int(m.group(1))).isoformat()
        u = m.group(4) if m.group(4).startswith("http") else "https://www.bi.go.id" + m.group(4)
        out.append(_rel("BI", "statement", d, d, u, title="Board of Governors meeting press release"))
    return out


def mas() -> list[dict]:
    url = "https://www.mas.gov.sg/monetary-policy/past-monetary-policy-decisions"
    raw = fetch(url, "MAS:past-decisions")
    out = []
    for m in re.finditer(r'href="(/news/monetary-policy-statements/\d{4}/[^"]+)"[^>]*>\s*(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{4})', raw):
        d = dt.date(int(m.group(4)), month_num(m.group(3)), int(m.group(2))).isoformat()
        out.append(_rel("MAS", "statement", d, d, "https://www.mas.gov.sg" + m.group(1), title="Monetary Policy Statement"))
    return out


def cbc() -> list[dict]:
    out = []
    for page in range(1, 7):
        try:
            raw = fetch(f"https://www.cbc.gov.tw/en/lp-448-2-{page}-60.html", "CBC:press-releases")
        except FetchError:
            break
        for href, title in re.findall(r'<a[^>]+href="([^"]+)"[^>]*title="([^"]+)"', raw):
            q = re.search(r"\(?(\d{4})\s*Q(\d)\)?", title.replace("（", "(").replace("）", ")"))
            if not q or int(q.group(1)) < 2025:
                continue
            kind = ("statement" if "Decision" in title else "minutes" if "Minutes" in title
                    else "pressconf" if "Press Conference" in title else None)
            if kind:
                out.append({"bank": "CBC", "kind": kind, "quarter": f"{q.group(1)}Q{q.group(2)}", "url": "https://www.cbc.gov.tw" + href,
                            "title": KIND_LABEL[kind] if kind != "pressconf" else "Press conference presentation", "status": "published"})
        if re.search(r"\(2024\s*Q", raw):
            break
    return out


def hkma() -> list[dict]:
    url = "https://www.hkma.gov.hk/eng/other-information/rss/rss_press-release.xml"
    raw = fetch(url, "HKMA:press-rss")
    out = []
    for blk in re.findall(r"<item>(.*?)</item>", raw, re.S):
        if "Base Rate" not in blk:
            continue
        link = re.search(r"<link>(.*?)</link>", blk, re.S)
        pub = re.search(r"<pubDate>(.*?)</pubDate>", blk, re.S)
        if link and pub:
            import email.utils
            p = email.utils.parsedate(pub.group(1))
            out.append(_rel("HKMA", "statement", None, dt.date(*p[:3]).isoformat(), htmllib.unescape(link.group(1).strip()),
                            title="Adjustment of Base Rate"))
    return out


def _cbc_dates(items: list[dict], meetings: list[dict]) -> list[dict]:
    """Taiwan lists documents by quarter: tie them to that quarter's meeting and
    read each document's own release date."""
    by_q = {f"{m['date'][:4]}Q{(int(m['date'][5:7]) - 1) // 3 + 1}": m["date"] for m in meetings}
    out = []
    for it in items:
        meet = by_q.get(it.pop("quarter", None))
        if not meet:
            continue
        it["meeting"] = meet
        if it["kind"] == "statement":
            it["date"] = meet
        else:
            try:
                t = html_to_text(fetch(it["url"], "CBC:release-page", timeout=25))
                rd = re.search(r"Release Date:\s*" + MONTHS + r" (\d{1,2}), (\d{4})", t)
                it["date"] = dt.date(int(rd.group(3)), month_num(rd.group(1)), int(rd.group(2))).isoformat() if rd else meet
            except FetchError:
                it["date"] = meet
        out.append(it)
    return out


def collect(sched: dict[str, list[dict]]) -> list[dict]:
    """All banks; a failing parser is logged and skipped. Kept from 2025 on."""
    tasks = {
        "FED": lambda: fed([m["date"] for m in sched.get("FED", [])]),
        "ECB": ecb, "BOE": lambda: boe(sched.get("BOE", [])), "BOJ": boj, "BOT": bot, "RBA": rba, "RBI": rbi,
        "BNM": lambda: bnm([m["date"] for m in sched.get("BNM", [])]), "BI": bi, "MAS": mas,
        "CBC": lambda: _cbc_dates(cbc(), sched.get("CBC", [])), "HKMA": hkma,
    }
    out, seen = [], set()
    for bank, fn in tasks.items():
        try:
            items = fn()
        except FetchError:
            continue
        except Exception as e:
            LOG.fail(f"{bank}:releases-parser", f"{type(e).__name__}: {e}")
            continue
        for r in items:
            if r.get("url"):
                r["url"] = r["url"].replace("]]>", "").strip()
            key = (r["bank"], r["kind"], r.get("meeting"), r.get("url") or r.get("date"))
            when = r.get("meeting") or r.get("date") or ""
            if key in seen or when < "2025-01-01":
                continue
            seen.add(key)
            out.append(r)
    # RBI future minutes: RBI has published each MPC's minutes 14 days after the meeting.
    have = {r["meeting"] for r in out if r["bank"] == "RBI" and r["kind"] == "minutes"}
    for m in sched.get("RBI", []):
        if m["date"] >= "2025-01-01" and m["date"] not in have and m["date"] >= (dt.date.today() - dt.timedelta(days=14)).isoformat():
            out.append(_rel("RBI", "minutes", m["date"], _plus(m["date"], 14), None, "scheduled",
                            "Pattern in RBI releases: minutes 14 days after the meeting"))
    return out
