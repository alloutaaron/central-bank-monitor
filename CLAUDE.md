# Central Bank Monitor: working rules

Public repo; the page is https://alloutaaron.github.io/central-bank-monitor/.
How it runs and how to fix it: `RUNBOOK.md`. Scoring: `methodology/hawk_dove_rubric.md`.

* Verify every fact (dates, rates, decisions, members) on the bank's own page
  before it goes in. Wikipedia may point to a source, never be one. If a fact
  cannot be verified, it shows as "Unavailable" or "TBC".
* Anything added to `seeds/` carries its official URL (`src`) and the date it
  was checked (`verified`).
* The job identifies itself as a bot. Sites that block it (RBNZ; BNM speech
  pages from some networks) are not worked around: use BIS, wires, or a hand
  check in a browser, and say which. SBV was removed from the page.
* Claude in the pipeline (the routine following `ROUTINE.md`, or the optional
  API path) only transforms fetched text (paraphrase, translate, score). It
  never supplies facts. Change `ROUTINE.md` and `scripts/check_outbox.py`
  together.
* Bump the `?v=` asset version in `docs/index.html` when changing `app.js` or
  `style.css`.
* Test a parser against the live page before committing; run
  `env -u ANTHROPIC_API_KEY .venv/bin/python -m pipeline.run --lookback-hours 6`
  for a quick no-AI end-to-end check.
