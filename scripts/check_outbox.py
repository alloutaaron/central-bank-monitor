#!/usr/bin/env python3
"""Checks language-step results before they are pushed. Standard library only,
so the Claude routine can run it anywhere:

    python3 scripts/check_outbox.py data/outbox/<file>.json

Exits non-zero (and says why) if any result does not match an item in
data/inbox/pending.json or breaks a rule."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANKS = set(json.loads((ROOT / "config" / "banks.json").read_text())["order"]) | {"NONE"}
STANCES = {"hawkish", "dovish", "neutral"}
QUOTES = re.compile(r"[\"“”„«»]")


def fail(errs, i, msg):
    errs.append(f"{i}: {msg}")


def main(paths):
    pending = json.loads((ROOT / "data" / "inbox" / "pending.json").read_text())
    ids = {"headlines": {x["id"] for x in pending["headlines"]}, "documents": {x["id"] for x in pending["documents"]},
           "expectations": {x["id"] for x in pending["expectations"]}}
    errs = []
    for path in paths:
        out = json.loads(Path(path).read_text())
        for r in out.get("headlines", []):
            i = r.get("id")
            if i not in ids["headlines"]:
                fail(errs, i, "id not in pending headlines")
            if r.get("bank") not in BANKS:
                fail(errs, i, f"bad bank {r.get('bank')}")
            if r.get("stance") not in STANCES or r.get("score") not in (-2, -1, 0, 1, 2):
                fail(errs, i, "bad stance/score")
            if r.get("kind") not in ("remark", "decision", "other"):
                fail(errs, i, "bad kind")
            if r.get("relevant"):
                para = r.get("paraphrase") or ""
                if not para or len(para.split()) > 45:
                    fail(errs, i, "paraphrase missing or over 45 words")
                if QUOTES.search(para):
                    fail(errs, i, "paraphrase contains quotation marks")
                if r.get("bank") == "NONE":
                    fail(errs, i, "relevant item without a bank")
                if r.get("kind") == "decision" and not re.fullmatch(r"[+-]?\d+", (r.get("decision_bp") or "").strip()):
                    fail(errs, i, "decision without decision_bp like +25 / 0 / -50")
        for r in out.get("documents", []):
            i = r.get("id")
            if i not in ids["documents"]:
                fail(errs, i, "id not in pending documents")
            if r.get("stance") not in STANCES or r.get("score") not in (-2, -1, 0, 1, 2):
                fail(errs, i, "bad stance/score")
            if r.get("relevant"):
                pts = r.get("points") or []
                if not (1 <= len(pts) <= 3) or any(len(p.split()) > 40 or QUOTES.search(p) for p in pts):
                    fail(errs, i, "points: 1-3 items, each at most 40 words, no quotation marks")
        for r in out.get("expectations", []):
            i = r.get("id")
            if i not in ids["expectations"]:
                fail(errs, i, "id not in pending expectations")
            if r.get("found"):
                if r.get("expected") not in ("hike", "hold", "cut"):
                    fail(errs, i, "expected must be hike/hold/cut when found")
                if not re.fullmatch(r"[+-]?\d+", (r.get("move_bp") or "").strip()):
                    fail(errs, i, "move_bp like +25 / 0 / -25")
                if not r.get("basis") or QUOTES.search(r.get("basis", "")):
                    fail(errs, i, "basis missing or contains quotation marks")
    if errs:
        print("FAILED:\n  " + "\n  ".join(errs[:60]))
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main(sys.argv[1:])
