"""Expected decisions and scheduled speeches.

* Forex Factory's public weekly calendar export: consensus forecasts for G10 and
  China rate decisions, plus scheduled G10 central-bank speeches (current week
  only, so each run archives what it sees).
An expectation is stored with its basis and date, and frozen once the meeting
has passed so 'expected vs actual' stays visible."""
from __future__ import annotations

import datetime as dt
import json
import re

from .common import ROOT, SGT, fetch, read_json, write_json, FetchError

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CCY_BANK = {"USD": "FED", "EUR": "ECB", "GBP": "BOE", "JPY": "BOJ", "AUD": "RBA", "NZD": "RBNZ", "CNY": "PBOC"}
DECISION_TITLES = re.compile(r"(Federal Funds Rate|Main Refinancing Rate|Deposit Facility Rate|Official Bank Rate|BOJ Policy Rate|"
                             r"Cash Rate|Official Cash Rate|1-y Loan Prime Rate)", re.I)
SPEECH_ARCHIVE = ROOT / "data" / "scheduled_speeches.json"


def forex_factory() -> list[dict]:
    try:
        return json.loads(fetch(FF_URL, "CONSENSUS:forexfactory", min_bytes=50))
    except (FetchError, ValueError):
        return []


def _pct(s: str | None) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", s or "")
    return float(m.group(0)) if m else None


def ff_expectations(ff: list[dict], meetings: list[dict]) -> dict:
    """meeting id -> expectation from Forex Factory forecasts (this week only)."""
    out = {}
    by_bank_date = {(m["bank"], m["date"]): m for m in meetings if m["type"] in ("meeting", "lpr")}
    for e in ff:
        bank = CCY_BANK.get(e.get("country"))
        if not bank or not DECISION_TITLES.search(e.get("title", "")):
            continue
        if bank == "ECB" and "Deposit" not in e["title"]:
            continue   # the deposit rate is the ECB's steering rate
        local = dt.datetime.fromisoformat(e["date"])
        cfg_tz = read_json(ROOT / "config" / "banks.json", {})["banks"][bank]["tz"]
        from zoneinfo import ZoneInfo
        ldate = local.astimezone(ZoneInfo(cfg_tz)).date().isoformat()
        m = by_bank_date.get((bank, ldate))
        fc, prev = _pct(e.get("forecast")), _pct(e.get("previous"))
        if not m or fc is None or prev is None:
            continue
        mv = int(round((fc - prev) * 100))
        label = "Hold" if mv == 0 else f"{mv:+d}bp"
        out[m["id"]] = {"move_bp": mv, "label": label, "basis": f"Consensus forecast {e['forecast']} (previous {e['previous']})",
                        "outlets": ["Forex Factory calendar"], "as_of": dt.datetime.now(SGT).date().isoformat(), "kind": "consensus"}
    return out


def update(expectations: dict, meetings: list[dict], today: dt.date, horizon_days: int = 21, ff: list[dict] | None = None) -> dict:
    """Refresh expectations for upcoming meetings; never overwrite a frozen one."""
    ffx = ff_expectations(ff if ff is not None else forex_factory(), meetings)
    for m in meetings:
        if m["type"] != "meeting" or m["bank"] in ("SBV",):
            continue
        d = dt.date.fromisoformat(m["date"])
        cur = expectations.get(m["id"])
        if cur and cur.get("frozen"):
            continue
        if d < today:
            if cur:
                cur["frozen"] = True
            continue
        if (d - today).days > horizon_days:
            continue
        new = ffx.get(m["id"])
        if new:
            expectations[m["id"]] = new
        if d == today and m["id"] in expectations:
            expectations[m["id"]]["frozen"] = True
    return expectations


_ECB_NAMES = (r"ECB|Lagarde|Lane|Schnabel|Cipollone|Elderson|Vujčić|Vujcic|Buba|Nagel|Moulin|Panetta|Rehn|Sleijpen|Kazaks|"
              r"Kazāks|Wunsch|Escrivá|Escriva|Stournaras|Makhlouf|Kocher|Kažimír|Kazimir|Šimkus|Simkus|Kaasik|Reinesch|Radev|"
              r"Demarco|Patsalides|Dolenc|Pereira|Žigman|Zigman")


def _is_cb_speech(bank: str, title: str) -> bool:
    """Speeches/testimony/press conferences by central-bank officials only
    (drops e.g. China's statistics bureau 'NBS Press Conference')."""
    if not re.search(r"Speaks|Testifies|Press Conference|Testimony", title):
        return False
    if not re.search(r"\b(Fed|FOMC|ECB|Buba|BOE|MPC|BOJ|RBA|RBNZ|PBOC|PBoC|Gov|Governor|President|Chair|Lagarde|Bailey|Ueda|Bullock)\b", title):
        return False
    return bank != "ECB" or bool(re.search(_ECB_NAMES, title))


def archive_speeches(ff: list[dict]) -> list[dict]:
    """Scheduled G10/China central-bank speeches from the weekly calendar,
    archived so past weeks stay on the calendar."""
    arch = read_json(SPEECH_ARCHIVE, []) or []
    seen = {(x["bank"], x["ts"], x["title"]) for x in arch}
    arch = [x for x in arch if _is_cb_speech(x["bank"], x["title"])]
    seen = {(x["bank"], x["ts"], x["title"]) for x in arch}
    for e in ff:
        bank = CCY_BANK.get(e.get("country"))
        t = e.get("title", "")
        if not bank or not _is_cb_speech(bank, t):
            continue
        ts = dt.datetime.fromisoformat(e["date"]).astimezone(SGT).isoformat(timespec="minutes")
        key = (bank, ts, t)
        if key not in seen:
            arch.append({"bank": bank, "ts": ts, "title": t, "impact": e.get("impact"), "src": "Forex Factory calendar"})
            seen.add(key)
    arch.sort(key=lambda x: x["ts"])
    write_json(SPEECH_ARCHIVE, arch)
    return arch
