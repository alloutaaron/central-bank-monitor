# Runbook: 15-minute refresh

## What runs, and when

* **Where:** GitHub Actions (GitHub's free job runner), workflow
  `.github/workflows/refresh.yml`. Your Mac does not need to be on.
* **When:** every 15 minutes, all day, started by an outside timer:
  a free cron-job.org job (Aaron's account, job "Central Bank Monitor
  refresh") calls GitHub's "run this workflow" address at :00, :15, :30 and
  :45 SGT. It uses a GitHub fine-grained token that can only start workflows on
  this repository (permission *Actions: write*); the token lives only in that
  cron-job.org job, never in this repository. Added 2026-10-31 because GitHub's
  own schedule ran only 4 times in 20 hours. GitHub's schedule is kept as an
  hourly backup (minute 7).
* **What it does** (`python -m pipeline.run`, about 1–2 minutes; no AI):
  reads official schedules, rate histories, decisions and release dates from
  each bank's own site where machine-readable (BoJ and HKMA decisions from
  their own statements and Base Rate releases), BIS (the central banks'
  statistics body) as a cross-check, and the hand-verified files in `seeds/`
  where a bank's page blocks the job or has no machine-readable version
  (meeting dates for BI, BNM, BoE 2025, BSP, MAS, RBA, RBI, RBNZ; decisions
  for BSP, RBI, RBNZ and pre-2024 RBA). Reads the newest First Squawk and
  Walter Bloomberg posts (public Telegram preview) every run, headlines from an
  allowlist of reputable outlets and the Forex Factory consensus about once an
  hour, and official speeches/statements (English pages). `pipeline/rules.py`
  keeps the headlines that quote a current committee member or report a bank's
  own decision, and shows them as published with their source. Then it commits
  the data (the git history is the rolling archive) and republishes the page.
* **Cost:** nothing. GitHub Actions and Pages are free for a public repository
  (last checked 2026-10; GitHub can change this). No Claude usage.
* **Retired 2026-10-30:** the daily AI language step (the Claude routine
  following `ROUTINE.md`; its code was removed 2026-10-31). Remarks are no longer
  paraphrased, translated or scored hawkish/dovish, and economists' polls are
  no longer read; the *Expected* column uses Forex Factory only.

## Checking that it ran

* The page header shows **Updated <date, time> SGT**: the last completed run.
  It adds **· overdue** when that is more than 2 hours old.
* The button beside it reads **Sources** when all is well, or **N stale** when
  a source failed on the latest run. Click it for details: which source failed
  and when it last worked. Old data from a failed source is never shown as fresh.
* On GitHub: repository → **Actions** tab → *Refresh*. A green tick is a
  successful run; click one to read its log. The log's last line reads
  `done: … feed items, failed sources: […]`.

## Running it by hand

```bash
gh workflow run refresh.yml --repo alloutaaron/central-bank-monitor
```

Backfill (also collects news headlines since a date; slower):

```bash
gh workflow run refresh.yml --repo alloutaaron/central-bank-monitor -f backfill=2026-04-01
```

## When something breaks

| Symptom | Likely cause | Fix |
|---|---|---|
| Header says *overdue*, Actions shows no recent run | The cron-job.org job stopped: its token expired (GitHub → Settings → Developer settings → Fine-grained tokens shows the date), or cron-job.org switched it off after 25 failed calls (it emails Aaron). The hourly GitHub backup can also be disabled after 60 days without repository activity | Regenerate the token and paste `Bearer <token>` into the job's *Authorization* header, then re-enable the job at console.cron-job.org; Actions tab → *Refresh* → **Enable workflow** if shown; run it by hand (command above) |
| Actions shows a run every 15 minutes, each failing | Not the timer: a bug or a source change | See the next row |
| Run failed (red cross) | A bug or a source changed its page layout badly enough to crash | Open the run log, copy the last 30 lines, and ask Claude Code in this folder to fix it |
| One bank shows *stale* | That source's page changed layout, or it blocked the job | Usually transient. If it lasts more than 2–3 days, ask Claude Code to update that parser in `pipeline/` |
| An irrelevant headline in the feed, or a remark missing | The plain rules in `pipeline/rules.py` (member names, bank names, decision words) misread it | Ask Claude Code to adjust `pipeline/rules.py`; test it on `data/statements/` before committing |
| A committee member is wrong | Membership changed | Update `seeds/members.json` (each entry lists its official source), commit, push |
| A meeting date moved | Banks occasionally reschedule | Banks with parsers update themselves; for RBA, RBNZ, BSP, RBI, BI, BNM edit `seeds/meetings.json` |

## Files that matter

* `pipeline/` – the job (Python). `run.py` is the refresh, `rules.py` decides
  which headlines and speeches go in the feed.
* `seeds/` – facts verified by hand from official pages, each with its URL and
  verification date.
* `data/statements/*.jsonl` – every feed item with its source and the raw
  text; items before 2026-10-30 were paraphrased and scored by the retired AI
  step (`model` field says which).
* `docs/` – the page (`index.html`, `app.js`, `style.css`) and its data.
