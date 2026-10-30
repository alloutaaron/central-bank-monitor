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
3. **Central bank speak**: newest first, each remark or decision headline
   shown as published, with its source and link. Items before 30 Oct 2026 are
   AI paraphrases from the earlier setup.
4. **Policy committees**: each bank's full verified committee; click a member
   for a short background (where verified on an official page) and their
   three latest remarks from the central bank speak feed.

Refreshed automatically every 15 minutes by a GitHub Actions job, with no AI:
plain rules (`pipeline/rules.py`) pick which headlines go in the feed. See
`RUNBOOK.md`.

## Sources

* Official central bank sites (schedules, decisions, rate histories, speeches,
  minutes; English pages), BIS policy-rate statistics as a
  cross-check.
* Telegram public previews of First Squawk and Walter Bloomberg.
* Headlines (not article text) from an allowlist of reputable outlets, used for
  remarks and decisions; Forex Factory's weekly calendar export for G10/China
  consensus and scheduled speeches.

Not investment advice. Headlines are quoted from their publishers, who own
them; the rules that select them can include an irrelevant item or miss one.
Every item's source and raw text is kept in `data/`.
