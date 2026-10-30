# Central Bank Monitor: working rules

Public repo; the page is https://alloutaaron.github.io/central-bank-monitor/.
How it runs and how to fix it: `RUNBOOK.md`. Refreshes every 15 minutes, no AI.

* Verify every fact (dates, rates, decisions, members) on the bank's own page
  before it goes in. Wikipedia may point to a source, never be one. If a fact
  cannot be verified, it shows as "Unavailable" or "TBC".
* Anything added to `seeds/` carries its official URL (`src`) and the date it
  was checked (`verified`).
* The job identifies itself as a bot. Sites that block it (RBNZ; BNM speech
  pages from some networks) are not worked around: use BIS, wires, or a hand
  check in a browser, and say which. SBV was removed from the page.
* No AI in the pipeline (since 2026-10-30, Aaron's decision). The feed quotes
  headlines and official titles as published, with outlet and link; Aaron
  accepted the copyright risk of quoting news headlines on a public page.
  `pipeline/rules.py` decides what goes in: test changes on the headlines in
  `data/statements/` and show what is kept and dropped before committing.
* Every run is a scheduled job hitting each bank's site; keep per-run requests
  small (fetch new documents only; cache parsed ones in `data/official_cache.json`).
* Bump the `?v=` asset version in `docs/index.html` when changing `app.js` or
  `style.css`.
* Test a parser against the live page before committing; run
  `.venv/bin/python -m pipeline.run --lookback-hours 6` on a copy of the
  project (it rewrites `data/` and `docs/data/`) for a quick end-to-end check.
