"""Shared helpers: polite HTTP fetching with a per-run source-health log, text
extraction, Singapore-time conversion and stable JSON files."""
from __future__ import annotations

import datetime as dt
import hashlib
import html as htmllib
import json
import os
import re
import ssl
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import certifi
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent.parent
SGT = ZoneInfo("Asia/Singapore")
UTC = dt.timezone.utc

# The job identifies itself honestly. Sites that refuse bots are reported as
# unavailable rather than worked around.
USER_AGENT = ("Mozilla/5.0 (compatible; CentralBankMonitor/1.0; "
              "+https://github.com/alloutaaron/central-bank-monitor)")

class _TLSAdapter(HTTPAdapter):
    """Full certificate verification, minus Python 3.13's opt-in "X509 strict"
    flag, which rejects valid chains whose intermediates lack a Subject Key
    Identifier (Taiwan's TWCA intermediate, used by cbc.gov.tw)."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context(cafile=certifi.where())
        ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def now_sgt() -> dt.datetime:
    return dt.datetime.now(SGT)


def today_sgt() -> dt.date:
    return now_sgt().date()


class SourceLog:
    """Records the outcome of every source used in a run, so the page can flag
    stale sources instead of silently showing old data."""

    def __init__(self):
        self.entries: dict[str, dict] = {}

    def ok(self, source_id: str, note: str = ""):
        e = self.entries.setdefault(source_id, {"ok": True, "errors": []})
        e["last_ok"] = now_sgt().isoformat(timespec="seconds")
        if note:
            e["note"] = note

    def fail(self, source_id: str, error: str):
        e = self.entries.setdefault(source_id, {"ok": True, "errors": []})
        e["ok"] = False
        e["errors"].append(error[:300])

    def as_dict(self) -> dict:
        return self.entries


LOG = SourceLog()

_session = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"})
        retry = Retry(total=3, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=("GET", "HEAD"))
        s.mount("https://", _TLSAdapter(max_retries=retry))
        s.mount("http://", HTTPAdapter(max_retries=retry))
        _session = s
    return _session


class FetchError(Exception):
    pass


def fetch(url: str, source_id: str, *, timeout: int = 45, headers: dict | None = None,
          binary: bool = False, min_bytes: int = 200, pause: float = 0.0):
    """GET a URL; log success/failure against source_id. Raises FetchError."""
    if pause:
        time.sleep(pause)
    try:
        r = session().get(url, timeout=timeout, headers=headers or {})
    except requests.RequestException as e:
        LOG.fail(source_id, f"{type(e).__name__}: {e}")
        raise FetchError(str(e)) from e
    if r.status_code != 200:
        LOG.fail(source_id, f"HTTP {r.status_code} for {url}")
        raise FetchError(f"HTTP {r.status_code}")
    if len(r.content) < min_bytes:
        LOG.fail(source_id, f"response too small ({len(r.content)} bytes) for {url}")
        raise FetchError("empty response")
    LOG.ok(source_id)
    if binary:
        return r.content
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return r.text


def html_to_text(raw: str) -> str:
    t = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d|td|th|table|section)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmllib.unescape(t)
    t = re.sub(r"[ \t\xa0​]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def to_sgt(date: dt.date, hhmm: str | None, tz: str) -> str | None:
    """Local announcement date/time -> ISO timestamp in SGT (None if no time)."""
    if not hhmm:
        return None
    h, m = map(int, hhmm.split(":"))
    local = dt.datetime(date.year, date.month, date.day, h, m, tzinfo=ZoneInfo(tz))
    return local.astimezone(SGT).isoformat(timespec="minutes")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, obj, compact: bool = False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    else:
        txt = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(txt + "\n", encoding="utf-8")
    os.replace(tmp, path)


_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def month_num(name: str) -> int:
    """'September', 'Sept.', 'Sep' -> 9."""
    return _MONTHS.index(name.strip(". ").lower()[:3]) + 1
