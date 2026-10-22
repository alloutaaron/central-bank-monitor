# Hawk/dove rubric (back end only, not shown on the page)

This file defines how every statement is scored and how members are placed on
the spectrum. The scoring prompt in `pipeline/llm.py` embeds this rubric.
Every scored statement, with its score and a one-line reason, is kept in
`data/statements/YYYY-MM.jsonl` so any placement can be audited.

## What "hawkish" and "dovish" mean here

* **Hawkish**: favouring tighter monetary policy (higher policy rates, rates held
  high for longer, earlier or larger hikes, a smaller balance sheet), usually
  because of concern about inflation. **Dovish**: favouring easier policy, usually
  because of concern about growth or employment. This follows the labelling used
  for central bank communication in *Trillion Dollar Words* (Shah, Paturi &
  Chava, ACL 2023, https://aclanthology.org/2023.acl-long.368/), which also
  stresses that single words are not enough: "increase" is hawkish or dovish
  depending on what is increasing.
* **Asia and emerging markets**: inflation-targeting central banks in emerging
  economies commonly combine the policy rate with FX intervention and
  macroprudential tools because of their sensitivity to capital flows and
  exchange-rate swings (BIS Annual Economic Report 2019, ch. II,
  https://www.bis.org/publ/arpdf/ar2019e2.htm; IMF, *Toward an Integrated Policy
  Framework*, 2020, https://www.imf.org/en/Publications/Policy-Papers/Issues/2020/10/08/Toward-an-Integrated-Policy-Framework-49813).
  So a central banker can be hawkish **without** an inflation argument: a
  commitment to use rates to stabilise a weakening currency or stem outflows is
  scored hawkish; tolerating depreciation to support growth is scored dovish.

## Reference point

A statement is scored against the bank's **current setting and latest official
guidance**, not against zero. In a hiking cycle, "we should pause" is dovish; in
a cutting cycle, "no more cuts for now" is hawkish.

## Per-statement score (integer, -2 to +2)

| Score | Meaning | Typical evidence |
|---|---|---|
| +2 | Explicitly hawkish | Votes or argues for a hike, a larger hike, or no cuts despite market pricing for cuts; dissents in favour of tighter policy |
| +1 | Hawkish lean | Stresses upside inflation risk, sticky inflation, de-anchoring expectations, overheating, tight labour market; "too early to ease"; uses rates to defend the currency or stem outflows; supports quantitative tightening or RRR hikes |
| 0 | Neutral / unclear | Data-dependent, balanced risks, purely factual description, or not about the policy outlook |
| -1 | Dovish lean | Stresses weakening growth or jobs, disinflation progress, downside risks; open to easing; tolerates a weaker currency to support growth; supports liquidity injections or RRR cuts |
| -2 | Explicitly dovish | Votes or argues for a cut, a larger cut, or no hikes despite pricing for hikes; dissents in favour of easier policy |

Rules:

1. Only remarks **attributable to a named member** count toward that member.
   A committee's joint statement counts toward no individual; the chair's own
   press-conference remarks count toward the chair.
2. Policy-irrelevant remarks (payments, supervision, climate, history) score 0
   and are excluded from placement.
3. Reported speech from wires is scored on what the official is reported to
   have said, never on the reporter's framing.
4. Non-English sources are scored on the original text, then paraphrased in
   English.

## Weights and aggregation

* Weight by evidence type: recorded vote or dissent **2.0**; official speech,
  testimony, press conference or interview **1.0**; wire or Telegram headline
  **0.75** (shorter, less context).
* Recency: each statement's weight decays with a **60-day half-life**; only the
  last **365 days** count. Recent remarks therefore dominate.
* Position = weighted mean score, from -2 (most dovish) to +2 (most hawkish).
  Every member with at least one scored, policy-relevant statement in the window
  is placed; that is a decisive call, including a placement at the centre.
* Members with no attributable remarks in the window are listed as "no recent
  attributable remarks" instead of being guessed.

## Known limitations

* Some committees publish views anonymously (BoK minutes, BoT and RBA vote
  counts, Taiwan CBC minutes). Anonymous views and vote counts are not attributed
  to individuals.
* Headline-only items lose nuance; they carry a lower weight for that reason.
* The model can misread a remark. The reason recorded next to every score is
  there so mistakes can be found and corrected.
