# Central Bank Monitor

Live page: https://alloutaaron.github.io/central-bank-monitor/

One page for 17 central banks (Fed, ECB, BoE, BoJ, BoK, PBoC, RBI, BNM, BI, BoT,
SBV, HKMA, MAS, BSP, Taiwan CBC, RBA, RBNZ):

1. **Calendar**: policy meetings and official speeches by month, with the rate
   going in, the expected decision (and its basis), the actual decision, and
   whether it matched. Times in SGT.
2. **Central bank speak**: newest first, close paraphrases (no quotes, no
   links), coloured by stance: muted orange hawkish, muted blue dovish, grey
   neutral.
3. **Hawk–dove spectrum**: each verified committee member placed from what
   they have said and how they voted, weighted toward recent remarks.

Refreshed automatically every morning before 08:00 SGT; see `RUNBOOK.md`.
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
