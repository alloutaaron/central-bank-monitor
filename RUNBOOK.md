# Runbook: daily refresh

## What runs, and when

* **Where:** GitHub Actions (GitHub's free job runner), workflow
  `.github/workflows/refresh.yml`. Your Mac does not need to be on.
* **When:** 05:23 SGT every day, plus a safety-net run at 06:53 SGT that only
  does work if the first run did not finish. GitHub warns that scheduled runs
  can be delayed or dropped at busy times, which is why there are two, both well
  before 08:00 SGT.
* **What it does** — three steps, each triggering the next:
  1. **Collect** (GitHub Actions, `python -m pipeline.run`, about 4–11 minutes).
     Reads official schedules, rate histories, decisions and release dates from
     each bank's own site where machine-readable, BIS (the central banks'
     statistics body) as a cross-check, and the hand-verified files in `seeds/`
     where a bank's page blocks the job or has no machine-readable version
     (meeting dates for BI, BNM, BoE 2025, BSP, MAS, RBA, RBI, RBNZ; decisions
     for BSP, RBI, RBNZ and pre-2024 RBA). Reads
     the last ~36 hours of First Squawk and Walter Bloomberg (public Telegram
     preview), headlines from an allowlist of reputable outlets, and official
     speeches/statements (original language). Publishes the page with the new
     rates and calendar, and queues all text that needs reading in
     `data/inbox/pending.json`.
  2. **Language step** (a Claude routine — a scheduled cloud session on your
     Claude plan — at 06:10 SGT). Follows `ROUTINE.md`: paraphrases, translates,
     tags hawkish/dovish and reads poll headlines for expected decisions, writes
     the results to `data/outbox/`, checks them with `scripts/check_outbox.py`
     and pushes. It only transforms text it was given; it never supplies facts.
  3. **Finalize** (GitHub Actions, `.github/workflows/finalize.yml`, ~2 minutes,
     starts automatically on that push). Merges the results into `data/` and
     republishes the page.
  Everything is committed, so the git history is the rolling archive.
* **Cost:** nothing extra. GitHub Actions and Pages are free for a public
  repository; the routine counts toward your Claude plan's usage like any other
  Claude Code session. No API key is needed (`pipeline/llm.py` has an optional
  API path that runs only if an `ANTHROPIC_API_KEY` secret is ever set).

## One-time setup: the routine

Needs GitHub connected to your Claude account (claude.ai/code → connect
GitHub; when GitHub asks, allow the Claude app on
`alloutaaron/central-bank-monitor` only). Then create it from Claude Code with
`/schedule`, or at claude.ai/code/routines:

* Name *Central Bank Monitor - daily language step*; repository
  `alloutaaron/central-bank-monitor`; environment *Default*; model Sonnet 5.5.
* Schedule daily 06:10 SGT (cron `10 22 * * *` in UTC).
* Prompt: follow `ROUTINE.md`, run the checker until it prints OK, push the new
  outbox files to `main` (not a `claude/` branch), end with a one-line summary.

## Checking that it ran

* The page header shows **UPD <date, time> SGT**: the last full collection
  (step 1). It adds **· OVERDUE** when that is more than 30 hours old.
* The button beside it reads **SOURCES** when all is well, **N STALE** when a
  source failed on the latest run, or **LANGUAGE STEP LATE** when text has been
  waiting more than 30 hours for step 2. Click it for details: which source
  failed and when it last worked, and when the language step last ran. Old data
  from a failed source is never shown as fresh.
* On GitHub: repository → **Actions** tab → *Daily refresh* and *Finalize*. A
  green tick is a successful run; click one to read its log. The refresh log's
  last line reads `done: … pending for language step: N, failed sources: […]`.
* The routine: claude.ai/code/routines → *Central Bank Monitor - daily language
  step* → **History**. A green status only means the session ran; open the run
  to read its one-line summary at the end.

## Running it by hand

```bash
gh workflow run refresh.yml --repo alloutaaron/central-bank-monitor
```

Backfill (re-reads history from a date; slower, and queues more text for the
language step):

```bash
gh workflow run refresh.yml --repo alloutaaron/central-bank-monitor -f backfill=2026-04-01
```

## When something breaks

| Symptom | Likely cause | Fix |
|---|---|---|
| Header says *refresh overdue*, Actions shows no run that day | GitHub skipped the schedule, or disabled it: public repos' scheduled workflows are switched off after 60 days without repository activity (the daily data commit should count as activity, but this is not verified) | Actions tab → *Daily refresh* → **Enable workflow** if shown, then run it by hand (command above) |
| Run failed (red cross) | A bug or a source changed its page layout badly enough to crash | Open the run log, copy the last 30 lines, and ask Claude Code in this folder to fix it |
| One bank shows *stale* | That source's page changed layout, or it blocked the job | Usually transient. If it lasts more than 2–3 days, ask Claude Code to update that parser in `pipeline/` |
| **LANGUAGE STEP LATE**; feed, spectrum and expectations stop changing | The routine did not run or did not push: GitHub disconnected from Claude (routines skip runs while disconnected and switch themselves off after 72 hours), plan usage limit reached, or its check failed | claude.ai/code/routines → open the routine → read the latest run. Reconnect GitHub at claude.ai/code if asked, switch the routine back on, then **Run now** |
| Language step ran but nothing new appeared | It ran before the collect step finished (GitHub delayed the 05:23 run), so it saw only yesterday's queue | Nothing to do: today's text waits in the queue and is processed the next morning. Or click **Run now** on the routine |
| *Finalize* failed (red cross) | The routine pushed a file the merge could not use | Open the Finalize log, copy the last 30 lines, and ask Claude Code in this folder to fix it; the routine's files are kept in `data/outbox/` |
| A committee member is wrong | Membership changed | Update `seeds/members.json` (each entry lists its official source), commit, push |
| A meeting date moved | Banks occasionally reschedule | Banks with parsers update themselves; for RBA, RBNZ, BSP, RBI, BI, BNM edit `seeds/meetings.json` |

## Files that matter

* `pipeline/` – the job (Python). `run.py` is the collect step, `finalize.py`
  merges the language step's results.
* `ROUTINE.md` – the routine's instructions; `scripts/check_outbox.py` checks
  its output before it is pushed. `data/inbox/pending.json` is the queue,
  `data/outbox/applied/` keeps every result file the page has used.
* `seeds/` – facts verified by hand from official pages, each with its URL and
  verification date.
* `methodology/hawk_dove_rubric.md` – how statements are scored and members
  placed (back end only; not shown on the page).
* `data/statements/*.jsonl` – every classified item with its score and reason:
  the audit trail for the spectrum.
* `docs/` – the page (`index.html`, `app.js`, `style.css`) and its data.
