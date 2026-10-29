# Central Bank Monitor

Live page: https://alloutaaron.github.io/central-bank-monitor/

One page for 16 central banks (Fed, ECB, BoE, BoJ, BoK, PBoC, RBI, BNM, BI, BoT,
HKMA, MAS, BSP, Taiwan CBC, RBA, RBNZ). Vietnam's SBV was dropped: its rate and
speech pages could not be read reliably.

1. **Policy rates**: each bank's current rate, last move, next decision (SGT)
   and the expected decision with its basis.
2. **Calendar**: policy meetings, minutes, accounts and other releases, and
   speeches by month, with the rate going in, the expected decision, the actual
   decision and whether it matched. Each meeting links to its official
   statement, minutes or PDF once published. Times in SGT.
3. **Central bank speak**: newest first, close paraphrases (no quotes), each
   linked to its source, coloured by stance: muted orange hawkish, muted blue
   dovish, grey neutral.
4. **Policy committees**: each bank's full verified committee; click a member
   for a short background (where verified on an official page) and their
   three latest remarks from the central bank speak feed.

Refreshed automatically every morning before 08:00 SGT: a GitHub Actions job
collects the data, a Claude routine on your plan does the reading and
paraphrasing, and a second job publishes the result. See `RUNBOOK.md`.
Scoring method: `methodology/hawk_dove_rubric.md`.

## Sources

* Official central bank sites (schedules, decisions, rate histories, speeches,
  minutes; original languages translated), BIS policy-rate statistics as a
  cross-check.
* Telegram public previews of First Squawk and Walter Bloomberg.
* Headlines (not article text) from an allowlist of reputable outlets, used for
  remarks and for polls/consensus; Forex Factory's weekly calendar export for
  G10/China consensus and scheduled speeches.

Not investment advice. Paraphrases are machine-generated from the sources above
and may contain errors; every item's source and reasoning is kept in `data/`.
