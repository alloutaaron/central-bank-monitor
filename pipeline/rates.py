"""Policy-rate histories. Each function returns a list of changes
[{"date": ISO, "level": "3.75-4.00" or "2.75", "mid": float, "kind": "decision"|"effective", "src": url}]
from the bank's own structured source where one is machine-readable. BIS
(the central banks' own statistics body) is the cross-check and the fallback
for sites that refuse bots. seeds/rates.json holds hand-verified histories."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
from functools import lru_cache

from .common import ROOT, fetch, html_to_text, month_num, read_json, today_sgt, write_json, FetchError, LOG

# China is left out: BIS reports the 1Y LPR, not the 7-day reverse repo policy rate.
BIS_AREAS = {"FED": "US", "ECB": "XM", "BOE": "GB", "BOJ": "JP", "BOK": "KR",
             "RBI": "IN", "BNM": "MY", "BI": "ID", "BOT": "TH", "HKMA": "HK", "BSP": "PH",
             "RBA": "AU", "RBNZ": "NZ"}


def _fmt(x: float) -> str:
    """5.5 -> '5.50', 3.875 -> '3.875'."""
    s = f"{x:.3f}"
    return s[:-1] if s.endswith("0") else s


@lru_cache(maxsize=1)
def bis_series(start: str = "2024-06-01") -> dict[str, list[tuple[str, float]]]:
    url = ("https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D."
           + "+".join(BIS_AREAS.values()) + f"?startPeriod={start}&format=csv")
    txt = fetch(url, "BIS:policy-rates", timeout=90)
    out: dict[str, list] = {}
    for r in csv.DictReader(io.StringIO(txt)):
        if r["OBS_VALUE"] not in ("", "NaN"):
            out.setdefault(r["REF_AREA"], []).append((r["TIME_PERIOD"], float(r["OBS_VALUE"])))
    return {k: sorted(v) for k, v in out.items()}


def bis_changes(bank: str) -> tuple[list[dict], str | None]:
    """Change points from BIS (effective dates), plus the last observation date."""
    s = bis_series().get(BIS_AREAS.get(bank, ""), [])
    out, prev = [], None
    for d, v in s:
        if prev is not None and abs(v - prev) > 1e-9:
            out.append({"date": d, "mid": v, "level": _fmt(v), "kind": "effective", "src": "BIS WS_CBPOL"})
        prev = v
    return out, (s[-1][0] if s else None)


def bis_level_on(bank: str, day: str) -> float | None:
    s = bis_series().get(BIS_AREAS.get(bank, ""), [])
    val = None
    for d, v in s:
        if d <= day:
            val = v
    return val


def fed() -> list[dict]:
    url = "https://www.federalreserve.gov/monetarypolicy/openmarket.htm"
    t = html_to_text(fetch(url, "FED:rate-history"))
    out = []
    for ym in re.finditer(r"\n\s*(20\d\d)\s*\n\s*Date\s*\n\s*Increase\s*\n\s*Decrease\s*\n\s*Level \(%\)(.*?)(?=Back to year navigation)", t, re.S):
        year, body = ym.groups()
        for m in re.finditer(r"(January|February|March|April|May|June|July|August|September|October|November|December) (\d{1,2})\*?\s*\n\s*(\d+|\.\.\.)\s*\n\s*(\d+|\.\.\.)\s*\n\s*([\d.]+)-([\d.]+)", body):
            mon, d, inc, dec, lo, hi = m.groups()
            date = dt.date(int(year), month_num(mon), int(d)).isoformat()
            out.append({"date": date, "level": f"{float(lo):.2f}-{float(hi):.2f}", "mid": (float(lo) + float(hi)) / 2,
                        "lower": float(lo), "upper": float(hi), "kind": "effective", "src": url})
    return sorted(out, key=lambda x: x["date"])


def ecb() -> list[dict]:
    """Deposit facility rate (the ECB's steering rate since Sept 2024), with MRO
    and marginal lending rates attached, from the ECB Data Portal API."""
    series = {}
    for key in ("DFR", "MRR_FR", "MLFR"):
        url = f"https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.{key}.LEV?startPeriod=2024-06-01&format=csvdata"
        txt = fetch(url, "ECB:data-api")
        series[key] = sorted((r["TIME_PERIOD"], float(r["OBS_VALUE"])) for r in csv.DictReader(io.StringIO(txt)) if r["OBS_VALUE"])
    out, prev = [], None
    mro = dict(series["MRR_FR"]); mlf = dict(series["MLFR"])
    for d, v in series["DFR"]:
        if prev is not None and abs(v - prev) > 1e-9:
            out.append({"date": d, "level": f"{v:.2f}", "mid": v, "kind": "effective",
                        "extra": {"MRO": mro.get(d), "MLF": mlf.get(d)},
                        "src": "https://data.ecb.europa.eu/ (FM.D.U2.EUR.4F.KR.DFR.LEV)"})
        prev = v
    return out


def boe() -> list[dict]:
    url = "https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp"
    t = html_to_text(fetch(url, "BOE:bank-rate"))
    out = []
    for m in re.finditer(r"(?m)^\s*(\d{2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{2})\s*\n\s*([\d.]+)\s*$", t):
        d, mon, yy, rate = m.groups()
        year = 2000 + int(yy) if int(yy) < 70 else 1900 + int(yy)
        date = dt.date(year, month_num(mon), int(d)).isoformat()
        if date >= "2024-06-01":
            out.append({"date": date, "level": f"{float(rate):.2f}", "mid": float(rate), "kind": "decision", "src": url})
    return sorted(out, key=lambda x: x["date"])


def bok() -> list[dict]:
    url = "https://www.bok.or.kr/portal/singl/baseRate/list.do?dataSeCd=01&menuNo=200643"
    t = html_to_text(fetch(url, "BOK:base-rate"))
    out = []
    for m in re.finditer(r"(20\d\d)\s*\n\s*(\d{2})월 (\d{2})일\s*\n\s*([\d.]+)", t):
        y, mo, d, rate = m.groups()
        date = dt.date(int(y), int(mo), int(d)).isoformat()
        if date >= "2024-06-01":
            out.append({"date": date, "level": f"{float(rate):.2f}", "mid": float(rate), "kind": "decision", "src": url})
    return sorted(out, key=lambda x: x["date"])


def bnm() -> list[dict]:
    """Every MPC decision (holds included) from BNM's official API."""
    out = []
    for y in range(2024, dt.date.today().year + 1):
        url = f"https://api.bnm.gov.my/public/opr/year/{y}"
        data = json.loads(fetch(url, "BNM:api", headers={"Accept": "application/vnd.BNM.API.v1+json"}, min_bytes=50))
        for r in data.get("data", []):
            out.append({"date": r["date"], "level": f"{float(r['new_opr_level']):.2f}", "mid": float(r["new_opr_level"]),
                        "change": float(r["change_in_opr"]), "kind": "decision", "src": url})
    return sorted(out, key=lambda x: x["date"])


def bi() -> list[dict]:
    """BI-Rate after every Board meeting (latest ten shown on the official page)."""
    url = "https://www.bi.go.id/en/statistik/indikator/bi-rate.aspx"
    t = html_to_text(fetch(url, "BI:bi-rate"))
    out = []
    for m in re.finditer(r"\n\s*\d{1,2}\s*\n\s*(\d{1,2}) (January|February|March|April|May|June|July|August|September|October|November|December) (20\d\d)\s*\n\s*([\d.]+) ?%", t):
        d, mon, y, rate = m.groups()
        out.append({"date": dt.date(int(y), month_num(mon), int(d)).isoformat(), "level": f"{float(rate):.2f}",
                    "mid": float(rate), "kind": "decision", "src": url})
    return sorted(out, key=lambda x: x["date"])


def bot() -> list[dict]:
    """Policy rate and MPC vote after each meeting, from the BoT's official
    downloadable table (the file name changes after every meeting)."""
    import openpyxl
    page = "https://www.bot.or.th/en/our-roles/monetary-policy/mpc-publication/policy-interest-rate.html"
    raw = fetch(page, "BOT:policy-rate")
    m = re.search(r'href=\\?"([^"\\]+\.xlsx)', raw)
    if not m:
        LOG.fail("BOT:policy-rate", "download link for the policy-rate table not found")
        return []
    link = "https://www.bot.or.th" + m.group(1) if m.group(1).startswith("/") else m.group(1)
    wb = openpyxl.load_workbook(io.BytesIO(fetch(link, "BOT:policy-rate-xlsx", binary=True)), data_only=True)
    # Columns: no. | date (Thai) | Date | meeting (Thai) | Meeting | decision (Thai) |
    # Decision | Policy rate | votes: Hold, +25, +50, -25, -50, Absent
    labels = ("hold", "+25", "+50", "-25", "-50", "absent")
    out = []
    for row in wb.active.iter_rows(values_only=True):
        if len(row) < 14 or not isinstance(row[2], dt.datetime) or not isinstance(row[7], (int, float)):
            continue
        if row[2].date().isoformat() < "2024-06-01":
            continue
        votes = {}
        for k, v in zip(labels, row[8:14]):  # cells may carry a footnote mark: "65/" = 6 votes, note 5
            n = int(v) if isinstance(v, (int, float)) else int(m.group(1)) if isinstance(v, str) and (m := re.match(r"\s*(\d)", v)) else 0
            if n:
                votes[k] = n
        out.append({"date": row[2].date().isoformat(), "level": f"{float(row[7]):.2f}", "mid": float(row[7]),
                    "decision_label": row[6], "votes": votes, "kind": "decision", "src": link})
    return sorted(out, key=lambda x: x["date"])


def mas() -> list[dict]:
    """MAS sets an exchange-rate band (S$NEER), not a policy rate. Returns each
    statement with the change to slope / width / centre ("-" = unchanged)."""
    url = "https://www.mas.gov.sg/monetary-policy/past-monetary-policy-decisions"
    lines = [ln.strip() for ln in html_to_text(fetch(url, "MAS:past-decisions")).split("\n") if ln.strip()]
    out = []
    for i, ln in enumerate(lines):
        m = re.fullmatch(r"(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (20\d\d)\*?", ln)
        if not m or int(m.group(3)) < 2024 or i + 3 >= len(lines):
            continue
        d, mon, y = m.groups()
        slope, width, centre = lines[i + 1], lines[i + 2], lines[i + 3]
        out.append({"date": dt.date(int(y), month_num(mon), int(d)).isoformat(), "kind": "decision", "src": url,
                    "slope": None if slope == "-" else slope, "width": None if width == "-" else width,
                    "centre": None if centre == "-" else centre})
    return sorted(out, key=lambda x: x["date"])


def cbc(meetings: list[dict]) -> list[dict]:
    """Discount rate from each quarterly decision release (see schedules.cbc)."""
    out = []
    for e in meetings:
        txt = e.get("decision_text") or ""
        m = re.search(r"discount rate[^%]*?(?:unchanged at|to) ([\d.]+)%", txt)
        if m:
            out.append({"date": e["date"], "level": _fmt(float(m.group(1))),
                        "mid": float(m.group(1)), "kind": "decision", "src": e["src"]})
    return out


def rba() -> list[dict]:
    """Cash rate target after every Board meeting (holds included). The table
    lists the effective date, the day after the decision."""
    url = "https://www.rba.gov.au/statistics/cash-rate/"
    t = html_to_text(fetch(url, "RBA:cash-rate"))
    out = []
    for m in re.finditer(r"(?m)^\s*(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (20\d\d)\s*\n\s*([+-]?[\d.]+)\s*\n\s*([\d.]+)\s*$", t):
        d, mon, y, chg, lvl = m.groups()
        eff = dt.date(int(y), month_num(mon), int(d))
        if eff.isoformat() >= "2024-06-01":
            out.append({"date": (eff - dt.timedelta(days=1)).isoformat(), "effective": eff.isoformat(),
                        "level": f"{float(lvl):.2f}", "mid": float(lvl), "kind": "decision", "src": url})
    return sorted(out, key=lambda x: x["date"])


def pboc_7d() -> tuple[list[dict], str | None]:
    """7-day reverse repo rate, the PBoC's main policy rate since mid-2024 (the
    LPRs are now quoted off it). History from seeds (PBOC_7D); the current
    level from the latest open market operations announcement on pbc.gov.cn.
    A level different from the last seed is recorded as a change on that
    announcement's date. Returns (changes, date of the latest announcement read)."""
    last = None
    out = [{"date": x["date"], "level": x["level"], "mid": float(x["level"]), "kind": "effective", "src": x["src"]}
           for x in seeded("PBOC_7D")]
    base = "https://www.pbc.gov.cn"
    try:
        raw = fetch(base + "/en/3688110/3688181/index.html", "PBOC:omo-list")
    except FetchError:
        return out, None   # seeds only; the failure is logged as a stale source
    links = re.findall(r'href="(/en/3688110/3688181/[^"]+/index\.html)"[^>]*>[^<]*Open Market Operations', raw)
    for href in links[:5]:   # the latest announcement normally has the 7-day operation; skip any that do not
        try:
            t = html_to_text(fetch(base + href, "PBOC:omo"))
        except FetchError:
            continue
        rate = re.search(r"Details of the 7-Day Reverse Repo Operations.*?7 days\s+([\d.]+)%", t, re.S)
        day = re.search(r"Open Market Operations Office, (\w+) (\d{1,2}), (20\d\d)", t)
        if rate and day:
            iso = dt.date(int(day[3]), month_num(day[1][:3]), int(day[2])).isoformat()
            lvl = float(rate[1])
            if not out or abs(out[-1]["mid"] - lvl) > 1e-9:
                out.append({"date": iso, "level": _fmt(lvl), "mid": lvl, "kind": "effective", "src": base + href})
            last = iso
            break
    return sorted(out, key=lambda x: x["date"]), last


CACHE = ROOT / "data" / "official_cache.json"   # decision documents already parsed (they never change)


def _cached(kind: str, url: str, parse) -> dict | None:
    cache = read_json(CACHE, {}) or {}
    hit = cache.get(kind, {}).get(url)
    if hit:
        return hit
    res = parse(url)
    if res:
        cache.setdefault(kind, {})[url] = res
        write_json(CACHE, cache)
    return res


def boj() -> list[dict]:
    """One row per meeting from the BoJ's own 'Statement on Monetary Policy'
    (or 'Change in the Guideline for Money Market Operations'), published at
    the decision: 'encourage the uncollateralized overnight call rate to remain
    at around X percent'."""
    base, out = "https://www.boj.or.jp", []
    for year in range(2025, today_sgt().year + 1):
        raw = fetch(f"{base}/en/mopo/mpmdeci/state_{year}/index.htm", "BOJ:statements")
        links = re.findall(r'href="(/en/mopo/mpmdeci/(?:mpr|state)_\d{4}/k(\d{6})a\.(?:pdf|htm))"[^>]*>\s*'
                           r'(?:Statement on Monetary Policy|Change in the Guideline for Money Market Operations)', raw)

        def parse(url: str) -> dict | None:
            data = fetch(url, "BOJ:statement", binary=True)
            if url.endswith(".pdf"):
                from pypdf import PdfReader
                text = " ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages[:2])
            else:
                text = html_to_text(data.decode("utf-8", "ignore"))
            # PDF text can split words ("o vernight"), so match with all spaces removed.
            m = re.search(r"encouragetheuncollateralizedovernightcallratetoremainataround([\d.]+)percent", re.sub(r"\s+", "", text))
            return {"level": m[1]} if m else None

        for href, ymd in dict.fromkeys(links):
            try:
                res = _cached("boj", base + href, parse)
            except FetchError:
                continue
            if res:
                lvl = float(res["level"])
                out.append({"date": f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:]}", "level": _fmt(lvl), "mid": lvl, "kind": "decision", "src": base + href})
    return sorted({x["date"]: x for x in out}.values(), key=lambda x: x["date"])


def hkma() -> list[dict]:
    """Base Rate changes from the HKMA's own 'Adjustment of Base Rate' press
    releases (issued the same day as a Fed move): 'the Base Rate has been set
    at X%'. No release means no change."""
    raw = fetch("https://www.hkma.gov.hk/eng/other-information/rss/rss_press-release.xml", "HKMA:press-releases")
    out = []
    for item in re.findall(r"<item>(.*?)</item>", raw, re.S):
        title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, re.S)
        link = re.search(r"<link>(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?</link>", item, re.S)
        if not (title and link and title[1].strip() == "Adjustment of Base Rate"):
            continue
        day = re.search(r"/(20\d\d)(\d\d)(\d\d)-\d+/?$", link[1])

        def parse(url: str) -> dict | None:
            m = re.search(r"Base Rate has been set at ([\d.]+)%", html_to_text(fetch(url, "HKMA:base-rate")))
            return {"level": m[1]} if m else None

        try:
            res = _cached("hkma", link[1], parse)
        except FetchError:
            continue
        if res and day:
            lvl = float(res["level"])
            out.append({"date": f"{day[1]}-{day[2]}-{day[3]}", "level": _fmt(lvl), "mid": lvl, "kind": "decision", "src": link[1]})
    return sorted(out, key=lambda x: x["date"])


OFFICIAL = {"FED": fed, "ECB": ecb, "BOE": boe, "BOK": bok, "BNM": bnm, "BI": bi, "BOT": bot, "RBA": rba}


def seeded(bank: str) -> list[dict]:
    return (read_json(ROOT / "seeds" / "rates.json", {}) or {}).get(bank, [])
