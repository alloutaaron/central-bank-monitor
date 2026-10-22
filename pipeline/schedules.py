"""Official meeting schedules. Each parser reads the bank's own page and returns
meetings as {"date": decision date (local, ISO), "days": "27-28", "flags": [...],
"src": url}. Banks whose sites block bots, or that publish schedules only in a
one-off press release, come from seeds/meetings.json (verified by hand from the
official page, with the URL and date of verification)."""
from __future__ import annotations

import datetime as dt
import re

from .common import ROOT, fetch, html_to_text, month_num, read_json, LOG, FetchError

SEEDS = ROOT / "seeds" / "meetings.json"
MON = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"


def _d(y, m, d) -> str:
    return dt.date(int(y), int(m), int(d)).isoformat()


def fed() -> list[dict]:
    url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    t = html_to_text(fetch(url, "FED:calendar"))
    out = []
    for ym in re.finditer(r"(\d{4}) FOMC Meetings(.*?)(?=\d{4} FOMC Meetings|$)", t, re.S):
        year, body = ym.group(1), ym.group(2)
        for m in re.finditer(r"\n\s*(January|February|March|April|May|June|July|August|September|October|November|December)"
                             r"(?:/(\w+))?\s*\n\s*(\d{1,2})-(\d{1,2})(\*?)(?:\s*\((unscheduled|notation vote)\))?", body):
            mon1, mon2, d1, d2, star, note = m.groups()
            if note:
                continue
            end_m = month_num(mon2) if mon2 else month_num(mon1)
            out.append({"date": _d(year, end_m, d2), "days": f"{d1}-{d2}",
                        "flags": ["SEP", "Press conference"] if star else ["Press conference"], "src": url})
    return out


def ecb() -> list[dict]:
    out = {}
    cal = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"
    t = html_to_text(fetch(cal, "ECB:calendar"))
    for m in re.finditer(r"(\d{2})/(\d{2})/(\d{4})\s*\n?\s*Governing Council of the ECB: monetary policy meeting[^\n]*\(Day 2\)", t):
        d, mo, y = m.groups()
        out[_d(y, mo, d)] = {"date": _d(y, mo, d), "flags": ["Press conference"], "src": cal}
    # Past meetings: the archive of monetary policy decision press releases.
    for y in range(2025, dt.date.today().year + 1):
        url = f"https://www.ecb.europa.eu/press/govcdec/mopo/{y}/html/index_include.en.html"
        try:
            raw = fetch(url, "ECB:decisions-archive")
        except FetchError:
            continue
        for blk in re.findall(r"<dt[^>]*>(.*?)</dd>", raw, re.S):
            txt = html_to_text(blk)
            dm = re.search(r"(\d{1,2}) (January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})", txt)
            if dm and re.search(r"Monetary policy decisions", txt, re.I):
                iso = _d(dm.group(3), month_num(dm.group(2)), dm.group(1))
                out.setdefault(iso, {"date": iso, "flags": ["Press conference"], "src": url})
    return sorted(out.values(), key=lambda x: x["date"])


def boe() -> list[dict]:
    url = "https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates"
    t = html_to_text(fetch(url, "BOE:mpc-dates"))
    out = []
    for sec in re.finditer(r"(\d{4}) (confirmed|provisional) dates(.*?)(?=\d{4} (?:confirmed|provisional) dates|Related links|$)", t, re.S):
        year, kind, body = sec.groups()
        for m in re.finditer(r"(?:Monday|Tuesday|Wednesday|Thursday|Friday) (\d{1,2}) (January|February|March|April|May|June|July|August|September|October|November|December)\s*\n?\s*([^\n]*)", body):
            d, mon, what = m.groups()
            if "MPC Summary" not in what and "Monetary Policy" not in what:
                continue
            flags = ["MPR"] if "Monetary Policy Report" in what else []
            if kind == "provisional":
                flags.append("Provisional")
            out.append({"date": _d(year, month_num(mon), d), "flags": flags, "src": url})
    return out


def boj() -> list[dict]:
    out = []
    for url, sid in (("https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm", "BOJ:mpm-schedule"),
                     ("https://www.boj.or.jp/en/mopo/mpmsche_minu/past.htm", "BOJ:mpm-schedule-past")):
        try:
            raw = fetch(url, sid)
        except FetchError:
            continue
        for ym in re.finditer(r'id="p(\d{4})"(.*?)(?=id="p\d{4}"|$)', raw, re.S):
            year, body = ym.group(1), html_to_text(ym.group(2))
            if int(year) < 2025:
                continue
            # MPM dates are the only two-day entries: "Jan. 22 (Thurs.), 23 (Fri.)"
            for m in re.finditer(MON + r"\s+(\d{1,2})\s*\(\w+\.?\),\s*(?:" + MON + r"\s+)?(\d{1,2})\s*\(\w+\.?\)", body):
                mon1, d1, mon2, d2 = m.groups()
                end_m = month_num(mon2 or mon1)
                out.append({"date": _d(year, end_m, d2), "days": f"{d1}-{d2}", "flags": [], "src": url})
    seen, res = set(), []
    for x in out:
        if x["date"] not in seen:
            seen.add(x["date"]); res.append(x)
    return res


def bok() -> list[dict]:
    out = []
    for y in (2025, 2026, 2027):
        url = f"https://www.bok.or.kr/portal/singl/crncyPolicyDrcMtg/listYear.do?mtgSe=A&menuNo=200755&pYear={y}"
        try:
            t = html_to_text(fetch(url, "BOK:schedule"))
        except FetchError:
            continue
        sel = re.search(r"회의일자(.*)", t, re.S)
        for m in re.finditer(r"(\d{1,2})월 ?(\d{1,2})일", sel.group(1) if sel else ""):
            out.append({"date": _d(y, m.group(1), m.group(2)), "flags": [], "src": url})
    seen, res = set(), []
    for x in out:
        if x["date"] not in seen:
            seen.add(x["date"]); res.append(x)
    return res


def bot() -> list[dict]:
    url = "https://www.bot.or.th/en/our-roles/monetary-policy/mpc-meeting.html"
    raw = fetch(url, "BOT:mpc-schedule").replace("\\r\\n", " ").replace('\\"', '"')
    out = []
    for sec in re.finditer(r"Schedule (\d{4})(.*?)(?=Schedule \d{4}|$)", raw, re.S):
        year, body = sec.group(1), html_to_text(sec.group(2))
        # Each row starts with the meeting number, then the decision date;
        # later columns (minutes, reports) carry other dates we must skip.
        for m in re.finditer(r"(?<![\d.])([1-8])\s+(?:Mon|Tue|Wed|Thu|Fri)\.\s*(\d{1,2})\s*" + MON + r"\s*(\d{4})", body):
            _, d, mon, y = m.groups()
            if y == year:
                out.append({"date": _d(y, month_num(mon), d), "flags": [], "src": url})
    seen, res = set(), []
    for x in out:
        if x["date"] not in seen:
            seen.add(x["date"]); res.append(x)
    return res


def bnm() -> list[dict]:
    """Past decisions from BNM's official API; the year's schedule from the
    Monetary Policy Statement that announced it (seeded)."""
    out = []
    for y in (2025, 2026):
        url = f"https://api.bnm.gov.my/public/opr/year/{y}"
        try:
            import json
            data = json.loads(fetch(url, "BNM:api", headers={"Accept": "application/vnd.BNM.API.v1+json"}, min_bytes=50))
        except (FetchError, ValueError):
            continue
        for r in data.get("data", []):
            out.append({"date": r["date"], "flags": [], "src": url})
    return out


def mas() -> list[dict]:
    url = "https://www.mas.gov.sg/monetary-policy/past-monetary-policy-decisions"
    t = html_to_text(fetch(url, "MAS:past-decisions"))
    out = []
    for m in re.finditer(r"\n\s*(\d{1,2}) " + MON + r" (20\d\d)\*?\s*\n", t):
        d, mon, y = m.groups()
        if int(y) >= 2025:
            out.append({"date": _d(y, month_num(mon), d), "flags": ["MPS"], "src": url})
    return out


def bi() -> list[dict]:
    url = "https://www.bi.go.id/en/statistik/indikator/bi-rate.aspx"
    t = html_to_text(fetch(url, "BI:bi-rate"))
    out = []
    for m in re.finditer(r"\n\s*\d{1,2}\s*\n\s*(\d{1,2}) (January|February|March|April|May|June|July|August|September|October|November|December) (20\d\d)\s*\n\s*[\d.]+ ?%", t):
        d, mon, y = m.groups()
        out.append({"date": _d(y, month_num(mon), d), "flags": [], "src": url})
    return out


def cbc() -> list[dict]:
    """Quarterly Board decisions, from the CBC's English press-release archive.
    Each decision page carries its release date and the rate sentence."""
    out, seen = [], set()
    for page in range(1, 7):
        url = f"https://www.cbc.gov.tw/en/lp-448-2-{page}-60.html"
        try:
            raw = fetch(url, "CBC:press-releases")
        except FetchError:
            break
        items = re.findall(r'<a[^>]+href="([^"]+)"[^>]*title="(Monetary Policy Decision of the Board Meeting[^"]*)"', raw)
        for href, title in items:
            q = re.search(r"\((\d{4})\s*Q(\d)\)", title)
            if not q or int(q.group(1)) < 2025 or href in seen:
                continue
            seen.add(href)
            link = "https://www.cbc.gov.tw" + href if href.startswith("/") else href
            t = html_to_text(fetch(link, "CBC:decision-page"))
            rd = re.search(r"Release Date:\s*(January|February|March|April|May|June|July|August|September|October|November|December) (\d{1,2}), (\d{4})", t)
            rate = re.search(r"The Board decided to ([^.]*discount rate[^.]*)\.", t)
            if rd:
                out.append({"date": _d(rd.group(3), month_num(rd.group(1)), rd.group(2)), "flags": [],
                            "src": link, "decision_text": rate.group(1) if rate else None})
        if any(re.search(r"\(2024\s*Q", t) for _, t in items):
            break
    return out


PARSERS = {"FED": fed, "ECB": ecb, "BOE": boe, "BOJ": boj, "BOK": bok, "BOT": bot,
           "BNM": bnm, "MAS": mas, "BI": bi, "CBC": cbc}


def lpr_history(start: dt.date, end: dt.date) -> list[dict]:
    """Official LPR fixings (date, 1Y, 5Y) from the National Interbank Funding
    Center (chinamoney.com.cn), the PBoC-authorised publisher. The API serves at
    most one year per request."""
    import json
    out, a = {}, start
    while a <= end:
        b = min(end, a + dt.timedelta(days=360))
        url = ("https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/LprHis?lang=CN"
               f"&strStartDate={a.isoformat()}&strEndDate={b.isoformat()}")
        data = json.loads(fetch(url, "PBOC:lpr-history", min_bytes=50))
        for r in data.get("records") or []:
            out[r["showDateCN"][:10]] = {"date": r["showDateCN"][:10], "1Y": float(r["1Y"]), "5Y": float(r["5Y"])}
        a = b + dt.timedelta(days=1)
    return sorted(out.values(), key=lambda x: x["date"])


def lpr_dates(start: dt.date, end: dt.date) -> list[dict]:
    """PBoC rule: LPR is published on the 20th of each month at 09:00 Beijing
    time, moved to the next working day if the 20th is a holiday. Weekends are
    applied here; mainland public holidays come from seeds (holiday_shifts)."""
    shifts = (read_json(SEEDS, {}).get("_lpr_holiday_shifts") or {})
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        d = dt.date(y, m, 20)
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        iso = shifts.get(d.isoformat(), d.isoformat())
        out.append({"date": iso, "flags": ["LPR"], "src": "https://www.chinamoney.com.cn/english/bmklpr/"})
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def collect() -> dict[str, list[dict]]:
    """Parsed schedules merged with seeds. Seeds win where a parser is down."""
    seeds = read_json(SEEDS, {})
    result = {}
    for bank, entries in seeds.items():
        if bank.startswith("_"):
            continue
        result[bank] = {e["date"]: dict(e, origin="seed") for e in entries}
    for bank, fn in PARSERS.items():
        try:
            parsed = fn()
        except FetchError:
            continue
        except Exception as e:  # parser broke: keep seeds, flag it
            LOG.fail(f"{bank}:schedule-parser", f"{type(e).__name__}: {e}")
            continue
        if not parsed:
            LOG.fail(f"{bank}:schedule-parser", "no dates found on the official page (layout change?)")
            continue
        cur = result.setdefault(bank, {})
        for e in parsed:
            old = cur.get(e["date"], {})
            merged = dict(old, **e, origin="official-page")
            merged["flags"] = sorted(set(old.get("flags", [])) | set(e.get("flags", [])))
            cur[e["date"]] = merged
    return {b: sorted(v.values(), key=lambda x: x["date"]) for b, v in result.items()}
