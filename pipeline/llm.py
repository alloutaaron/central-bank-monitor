"""All calls to Claude live here. Claude never supplies facts: it only reads text
the pipeline fetched (headlines, speeches, statements) and returns structured
judgements (paraphrase, translation, hawk/dove score, expected move), each tied
back to the item it read. Without an API key every function returns None and
the page shows those items as unclassified."""
from __future__ import annotations

import json
import os
import time

from .common import ROOT, LOG, read_json

MODEL = "claude-opus-5-5"
# Anthropic list prices per million tokens (claude-api reference, cached 2026-10-06).
PRICE_IN, PRICE_OUT = 4.00, 20.00

USAGE = {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "failures": 0}
_client = None


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(max_retries=3, timeout=300)
    return _client


def cost_usd() -> float:
    return round(USAGE["input"] / 1e6 * PRICE_IN + USAGE["output"] / 1e6 * PRICE_OUT, 4)


BANK_CODES = ["FED", "ECB", "BOE", "BOJ", "BOK", "PBOC", "RBI", "BNM", "BI", "BOT", "SBV",
              "HKMA", "MAS", "BSP", "CBC", "RBA", "RBNZ"]


def _roster() -> str:
    cfg = read_json(ROOT / "config" / "banks.json", {})["banks"]
    mem = read_json(ROOT / "seeds" / "members.json", {})
    lines = []
    for code in BANK_CODES:
        names = ", ".join(m["name"] for m in mem.get(code, {}).get("members", []))
        lines.append(f"{code} = {cfg[code]['name']}" + (f" (committee: {names})" if names else ""))
    return "\n".join(lines)


RUBRIC = """Score what a named official of one of the 17 central banks below said or did, for the
direction of monetary policy they favour, relative to the bank's CURRENT setting and latest guidance.
+2 explicitly hawkish: votes/argues for a hike, a larger hike, or no cuts despite pricing for cuts; hawkish dissent.
+1 hawkish lean: stresses upside inflation risks, sticky inflation, overheating, tight labour market, "too early to ease";
   uses rates to defend the currency or stem capital outflows (counts even without an inflation argument); supports QT/RRR hikes.
 0 neutral: balanced, data-dependent, factual, or not about the policy outlook.
-1 dovish lean: stresses weak growth or jobs, disinflation, downside risks, openness to easing; tolerates a weaker currency to
   support growth; supports liquidity injections/RRR cuts.
-2 explicitly dovish: votes/argues for a cut, a larger cut, or no hikes despite pricing for hikes; dovish dissent.
In a hiking cycle "pause" is dovish; in a cutting cycle "no more cuts" is hawkish. Score the official's words, not the reporter's framing."""

STYLE = """Paraphrase rules: English; a close paraphrase of what the official said, at most 35 words; never use quotation
marks or quote verbatim; no outlet names, links, hashtags or emojis; keep numbers, dates and rate levels exactly as given;
translate faithfully when the source is not English. Never add facts that are not in the text you were given."""


def _system(task: str) -> list[dict]:
    text = (f"You are a careful central-bank analyst building a monitoring dashboard.\n\n{task}\n\n"
            f"Central banks (code = name, verified committee members):\n{_roster()}\n\n"
            f"Hawk/dove rubric:\n{RUBRIC}\n\n{STYLE}")
    return [{"type": "text", "text": text}]


def _call(task: str, user: str, schema: dict, max_tokens: int = 16000, effort: str = "low"):
    if not available():
        return None
    import anthropic
    kwargs = dict(model=MODEL, max_tokens=max_tokens, system=_system(task),
                  messages=[{"role": "user", "content": user}],
                  output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
                  cache_control={"type": "ephemeral"})
    for attempt in range(2):
        try:
            if attempt == 0:  # server-side fallback on refusal, as the API docs recommend
                resp = client().beta.messages.create(betas=["server-side-fallback-2026-07-01"],
                                                     fallbacks="default", **kwargs)
            else:
                resp = client().messages.create(**kwargs)
            break
        except anthropic.BadRequestError as e:
            if attempt == 0:
                continue  # retry without the beta fallback parameter
            LOG.fail("AI:claude", f"bad request: {e.message[:200]}")
            USAGE["failures"] += 1
            return None
        except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as e:
            time.sleep(20)
            if attempt == 1:
                LOG.fail("AI:claude", f"{type(e).__name__}")
                USAGE["failures"] += 1
                return None
        except anthropic.APIStatusError as e:
            LOG.fail("AI:claude", f"HTTP {e.status_code}: {str(e)[:200]}")
            USAGE["failures"] += 1
            return None
    USAGE["calls"] += 1
    u = resp.usage
    USAGE["input"] += (u.input_tokens or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0)
    USAGE["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
    USAGE["output"] += u.output_tokens or 0
    if resp.stop_reason in ("refusal", "max_tokens"):
        LOG.fail("AI:claude", f"stop_reason={resp.stop_reason}")
        USAGE["failures"] += 1
        return None
    text = next((b.text for b in resp.content if b.type == "text"), None)
    try:
        out = json.loads(text) if text else None
    except json.JSONDecodeError:
        out = None
    if out is None:
        LOG.fail("AI:claude", "unparseable response")
        USAGE["failures"] += 1
    else:
        LOG.ok("AI:claude")
    return out


SCORE = {"type": "integer", "enum": [-2, -1, 0, 1, 2]}
STANCE = {"type": "string", "enum": ["hawkish", "dovish", "neutral"]}
BANK = {"type": "string", "enum": BANK_CODES + ["NONE"]}


def classify_headlines(items: list[dict]) -> list[dict] | None:
    """items: [{id, ts, text}] from Telegram or news headlines."""
    schema = {"type": "object", "additionalProperties": False, "required": ["items"], "properties": {"items": {
        "type": "array", "items": {"type": "object", "additionalProperties": False,
            "required": ["id", "relevant", "bank", "speaker", "role", "kind", "paraphrase", "stance", "score", "reason", "decision_bp", "decision_level"],
            "properties": {
                "id": {"type": "string"}, "relevant": {"type": "boolean"}, "bank": BANK,
                "speaker": {"type": "string"}, "role": {"type": "string"},
                "kind": {"type": "string", "enum": ["remark", "decision", "other"]},
                "paraphrase": {"type": "string"}, "stance": STANCE, "score": SCORE,
                "reason": {"type": "string"},
                "decision_bp": {"type": "string"}, "decision_level": {"type": "string"}}}}}}
    task = ("Classify each headline. relevant=true only if it reports what a NAMED official of one of the 17 banks below said, "
            "or an official policy decision by one of them. Analysts, economists, markets, politicians and other central banks "
            "(SNB, BoC, Banxico, Riksbank, etc.) are not relevant. kind='decision' for announced policy decisions (fill decision_bp "
            "like '+25', '0', '-50' and decision_level like '3.75-4.00' or '5.50'; else empty strings). speaker = full name as in the "
            "roster when identifiable, else as written; role = their title. reason = at most 15 words on why that score. For "
            "irrelevant items return relevant=false, bank NONE, empty strings, stance neutral, score 0.")
    out = []
    for i in range(0, len(items), 40):
        chunk = items[i:i + 40]
        user = "Headlines (id | time SGT | text):\n" + "\n".join(f"{x['id']} | {x['ts']} | {x['text']}" for x in chunk)
        res = _call(task, user, schema)
        if res is None:
            return None if not out else out
        out.extend(res.get("items", []))
    return out


def process_document(bank: str, title: str, date: str, lang: str, text: str) -> dict | None:
    schema = {"type": "object", "additionalProperties": False,
              "required": ["relevant", "speaker", "role", "points", "stance", "score", "reason"],
              "properties": {"relevant": {"type": "boolean"}, "speaker": {"type": "string"}, "role": {"type": "string"},
                             "points": {"type": "array", "items": {"type": "string"}},
                             "stance": STANCE, "score": SCORE, "reason": {"type": "string"}}}
    task = ("Read one official document (speech, testimony, press conference, interview, statement or minutes) from a central bank. "
            "relevant=true only if it says something about the monetary-policy outlook (rates, inflation, growth, FX, liquidity). "
            "speaker = the official whose views these are (for a committee statement, the chair if they delivered it; otherwise "
            "the committee name). points = 1-3 short English paraphrases of the policy-relevant remarks, each at most 30 words. "
            "reason = at most 15 words.")
    user = f"Bank: {bank}\nDate: {date}\nLanguage: {lang}\nTitle: {title}\n\nText (may be truncated):\n{text[:24000]}"
    return _call(task, user, schema, max_tokens=8000)


def extract_expectation(bank: str, meeting_date: str, current: str, headlines: list[str]) -> dict | None:
    schema = {"type": "object", "additionalProperties": False,
              "required": ["found", "expected", "move_bp", "basis", "outlets"],
              "properties": {"found": {"type": "boolean"},
                             "expected": {"type": "string", "enum": ["hike", "hold", "cut", "split"]},
                             "move_bp": {"type": "string"}, "basis": {"type": "string"},
                             "outlets": {"type": "array", "items": {"type": "string"}}}}
    task = ("From the dated news headlines below, determine what economists' polls or market pricing EXPECT the central bank to "
            "decide at the stated meeting. Use only polls, surveys, consensus or market-pricing reports (not a single bank's view, "
            "unless several agree). found=false if the headlines do not establish an expectation for THIS meeting. move_bp like "
            "'+25', '0', '-25'. basis = one short paraphrase (at most 20 words) of the evidence, e.g. 'Reuters poll: most economists "
            "expect a hold'. outlets = the outlets cited.")
    user = (f"Bank: {bank}\nMeeting decision date: {meeting_date}\nCurrent setting: {current}\n\nHeadlines (date | outlet | title):\n"
            + "\n".join(headlines[:60]))
    return _call(task, user, schema, max_tokens=4000)


def extract_decision(bank: str, meeting_date: str, before: str, texts: list[str]) -> dict | None:
    schema = {"type": "object", "additionalProperties": False,
              "required": ["found", "move_bp", "new_level", "summary"],
              "properties": {"found": {"type": "boolean"}, "move_bp": {"type": "string"},
                             "new_level": {"type": "string"}, "summary": {"type": "string"}}}
    task = ("Determine the monetary-policy decision the bank announced on or just before the stated date, using only the texts "
            "given. found=false if they do not state it. move_bp like '+25', '0', '-50'; new_level is the policy-rate level after "
            "the decision as written (or empty). summary = at most 20 words, paraphrased.")
    user = f"Bank: {bank}\nDecision date: {meeting_date}\nSetting before: {before}\n\nTexts:\n" + "\n---\n".join(t[:6000] for t in texts[:8])
    return _call(task, user, schema, max_tokens=4000)
