"""Data check, run at the end of every refresh: lists what a person should look
at, and keeps one GitHub issue in step with that list, so Aaron is emailed
only when the list changes (new problem, or all clear).

* a past meeting with no decision 2+ days later (official data and wires silent)
* a decision still only "per wires" 7+ days later
* a policy rate that disagrees with BIS once BIS has data after the last decision
* a source that has been failing for 3+ days

Without GITHUB_TOKEN (a run on a laptop) the list is printed, nothing is sent.
"""
from __future__ import annotations

import datetime as dt
import os
import re

import requests

from . import rates
from .common import ROOT, now_sgt, read_json, write_json, FetchError

STATE = ROOT / "data" / "check.json"
TITLE = "Data check: something on the page needs a look"
SKIP_BIS = {"PBOC", "MAS", "CBC"}   # BIS reports China's 1Y LPR, not the 7-day repo; MAS has no rate; no BIS daily series for Taiwan


def _mid(level: str | None) -> float | None:
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", level or "")]
    return sum(nums) / len(nums) if nums else None


def problems(recs: list[dict], today: dt.date) -> list[dict]:
    out = []
    for r in recs:
        if r["type"] != "meeting" or r["date"] > today.isoformat():
            continue
        age = (today - dt.date.fromisoformat(r["date"])).days
        dec = r.get("decision") or {}
        if not dec and age >= 2:
            fix = ("Check the bank's site by hand and add the decision to seeds/rates.json (with src and verified)."
                   if r["bank"] in ("RBNZ", "BSP", "RBI") else
                   "The bank's own data should have shown it: ask Claude Code in this folder to check that bank's parser.")
            out.append({"key": f"awaiting:{r['id']}", "text": f"{r['bank']} meeting on {r['date']} still shows no decision after {age} days. {fix}"})
        elif dec.get("source_kind") == "wires" and age >= 7:
            out.append({"key": f"wires:{r['id']}", "text": f"{r['bank']} {r['date']} decision is still only 'per wires' after {age} days "
                        f"({dec.get('label')}). Confirm it on the bank's site and add it to seeds/rates.json."})
    banks = {b["code"]: b for b in (read_json(ROOT / "docs" / "data" / "banks.json", {}) or {}).get("banks", [])}
    try:
        series = rates.bis_series()
    except FetchError:
        series = {}
    for code, b in banks.items():
        area = rates.BIS_AREAS.get(code)
        obs = series.get(area) if area and code not in SKIP_BIS else None
        page, as_of = _mid((b.get("rate") or {}).get("level")), (b.get("last") or {}).get("date") or (b.get("rate") or {}).get("as_of")
        if not obs or page is None or not as_of:
            continue
        d, v = obs[-1]
        if d >= (dt.date.fromisoformat(as_of) + dt.timedelta(days=7)).isoformat() and abs(v - page) > 1e-6:
            out.append({"key": f"bis:{code}:{d}:{v}", "text": f"{code}: the page shows {b['rate']['level']} but BIS shows {v:g}% on {d}. "
                        "A decision may have been missed or misread."})
    meta = read_json(ROOT / "docs" / "data" / "meta.json", {}) or {}
    for s in meta.get("stale") or []:
        last = (s.get("last_ok") or "")[:10]
        if last and (today - dt.date.fromisoformat(last)).days >= 3:
            out.append({"key": f"stale:{s['source']}", "text": f"Source {s['source']} has failed since {last}: {str(s.get('error'))[:160]}. "
                        "If its page changed layout, ask Claude Code in this folder to update the parser."})
    return sorted(out, key=lambda p: p["key"])


def _gh(method: str, path: str, **kw):
    r = requests.request(method, f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}{path}", timeout=20,
                         headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"}, **kw)
    r.raise_for_status()
    return r.json() if r.content else None


def run(recs: list[dict], today: dt.date):
    found = problems(recs, today)
    state = read_json(STATE, {}) or {}
    keys = [p["key"] for p in found]
    for p in found:
        print("check:", p["text"], flush=True)
    if keys == state.get("keys"):
        return
    new = [p for p in found if p["key"] not in set(state.get("keys") or [])]
    if not os.environ.get("GITHUB_TOKEN"):
        print(f"check: {len(found)} problem(s); not sent (no GITHUB_TOKEN)", flush=True)
        return
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    body = (f"@{owner} the automatic data check found {len(found)} thing(s) to look at "
            f"(checked {now_sgt():%d %b %H:%M} SGT):\n\n" + "\n".join(f"- {p['text']}" for p in found) +
            "\n\nThis issue updates itself and closes when everything is clear.")
    try:
        issue = state.get("issue")
        if issue and _gh("GET", f"/issues/{issue}")["state"] != "open":
            issue = None
        if found and not issue:
            issue = _gh("POST", "/issues", json={"title": TITLE, "body": body})["number"]
        elif found:
            _gh("PATCH", f"/issues/{issue}", json={"body": body})
            if new:
                _gh("POST", f"/issues/{issue}/comments", json={"body": f"@{owner} new:\n" + "\n".join(f"- {p['text']}" for p in new)})
        elif issue:
            _gh("POST", f"/issues/{issue}/comments", json={"body": "All clear: nothing needs a look any more."})
            _gh("PATCH", f"/issues/{issue}", json={"state": "closed"})
            issue = None
    except (requests.RequestException, KeyError) as e:
        print(f"check: could not update the GitHub issue: {e}", flush=True)
        return
    write_json(STATE, {"keys": keys, "issue": issue, "updated": now_sgt().isoformat(timespec="minutes")})
