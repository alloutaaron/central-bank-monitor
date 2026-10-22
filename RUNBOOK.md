# Runbook: daily refresh

## What runs, and when

* **Where:** GitHub Actions (GitHub's free job runner), workflow
  `.github/workflows/refresh.yml`. Your Mac does not need to be on.
* **When:** 05:23 SGT every day, plus a safety-net run at 06:53 SGT that only
  does work if the first run did not finish. GitHub warns that scheduled runs
  can be delayed or dropped at busy times, which is why there are two, both well
  before 08:00 SGT.
* **What it does** (`python -m pipeline.run`):
  1. Reads official schedules, rate histories and decisions from each bank's own
     site where machine-readable, BIS (the central banks' statistics body) as a
     cross-check, and the hand-verified files in `seeds/` for sites that block
     automated access (RBA, RBNZ, BSP).
  2. Reads the last ~36 hours of First Squawk and Walter Bloomberg (public
     Telegram preview), headlines from an allowlist of reputable outlets, and
     official speeches/statements (original language).
  3. Sends that text to Claude (Opus 5.5) to paraphrase, translate, tag
     hawkish/dovish and read poll headlines. Claude never supplies facts.
  4. Writes the page's data (`docs/data/`) and the audit trail (`data/`),
     commits them (the git history is the rolling archive) and publishes the
     page with GitHub Pages.
* **Cost:** roughly US$10–25 a month in Claude API usage (estimate; each run
  prints its own cost in the log, and the page's data records it in
  `docs/data/meta.json`).

## Checking that it ran

* The page header shows **Updated <date, time> SGT**. If it says *refresh
  overdue*, the latest run did not complete.
* The **Sources** / **N sources stale** button lists every source that failed
  on the latest run and when it last worked. Old data from a failed source is
  never shown as fresh.
* On GitHub: repository → **Actions** tab → *Daily refresh*. A green tick is a
  successful run; click a run to read its log. The last log line reads
  `done: … failed sources: […]`.

## Running it by hand

```bash
gh workflow run refresh.yml --repo alloutaaron/central-bank-monitor
```

Backfill (re-reads history from a date; slower, costs a few dollars):

```bash
gh workflow run refresh.yml --repo alloutaaron/central-bank-monitor -f backfill=2026-04-01
```

## When something breaks

| Symptom | Likely cause | Fix |
|---|---|---|
| Header says *refresh overdue*, Actions shows no run that day | GitHub skipped the schedule, or disabled it: public repos' scheduled workflows are switched off after 60 days without repository activity (the daily data commit should count as activity, but this is not verified) | Actions tab → *Daily refresh* → **Enable workflow** if shown, then run it by hand (command above) |
| Run failed (red cross) | A bug or a source changed its page layout badly enough to crash | Open the run log, copy the last 30 lines, and ask Claude Code in this folder to fix it |
| One bank shows *stale* | That source's page changed layout, or it blocked the job | Usually transient. If it lasts more than 2–3 days, ask Claude Code to update that parser in `pipeline/` |
| Feed and spectrum stop changing; *AI step not run* in the Sources panel | API key missing, expired or out of credit | platform.claude.com → check credit / create a new key, then `gh secret set ANTHROPIC_API_KEY --repo alloutaaron/central-bank-monitor` |
| A committee member is wrong | Membership changed | Update `seeds/members.json` (each entry lists its official source), commit, push |
| A meeting date moved | Banks occasionally reschedule | Banks with parsers update themselves; for RBA, RBNZ, BSP, RBI, BI, BNM edit `seeds/meetings.json` |

## Files that matter

* `pipeline/` – the job (Python). `run.py` is the entry point.
* `seeds/` – facts verified by hand from official pages, each with its URL and
  verification date.
* `methodology/hawk_dove_rubric.md` – how statements are scored and members
  placed (back end only; not shown on the page).
* `data/statements/*.jsonl` – every classified item with its score and reason:
  the audit trail for the spectrum.
* `docs/` – the page (`index.html`, `app.js`, `style.css`) and its data.
