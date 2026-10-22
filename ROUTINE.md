# Daily language step (run by the Claude routine)

You are the language step of the Central Bank Monitor. The morning collection
job has queued text in `data/inbox/pending.json`. Turn it into structured
results, check them, and push them. Do not change any other file.

## 1. Read

* `data/inbox/pending.json`: `headlines`, `documents`, `expectations` to process.
* `config/banks.json`: the bank codes (`order`) and names.
* `seeds/members.json`: each bank's verified committee members (use these exact
  names for `speaker` when the person is on the list).
* `methodology/hawk_dove_rubric.md`: how to score stance. Follow it exactly.

If all three lists are empty, stop: nothing to do, no commit.

## 2. Write results

Process everything in `pending.json`. Write one or more files
`data/outbox/<YYYYMMDD-HHMM>-<n>.json` (at most 120 headlines per file), each:

```json
{"headlines": [...], "documents": [...], "expectations": [...]}
```

**headlines** — one object per pending headline, same `id`:
`{"id", "relevant": bool, "bank": code or "NONE", "speaker", "role",
"kind": "remark"|"decision"|"other", "paraphrase", "stance": "hawkish"|"dovish"|"neutral",
"score": -2..2, "reason", "decision_bp", "decision_level"}`

* `relevant` = true only if the headline reports what a **named official** of
  one of the banks in `config/banks.json` said, or an official policy decision
  by one of them. Analysts, economists, markets, politicians and other central
  banks (SNB, BoC, Banxico, Riksbank, etc.) are not relevant. Former officials
  are not relevant.
* `kind` = "decision" for an announced policy decision; then `decision_bp` like
  "+25", "0", "-50" and `decision_level` like "3.75-4.00" or "5.50". Otherwise
  both are "".
* `paraphrase`: English, a close paraphrase of what the official said, at most
  35 words. No quotation marks, no verbatim quotes, no outlet names, links,
  hashtags or emojis. Keep numbers, dates and rate levels exactly as given.
* `stance`/`score`: per the rubric, relative to the bank's current setting. The
  headline's own words, not the reporter's framing. `reason`: at most 15 words.
* Irrelevant items: `relevant` false, `bank` "NONE", empty strings, `stance`
  "neutral", `score` 0.

**documents** — one per pending document, same `id`:
`{"id", "relevant", "speaker", "role", "points": [1-3 strings], "stance", "score", "reason"}`

* Documents are official speeches, statements, minutes or press conferences,
  often not in English (`lang`). Read the original; write `points` as 1-3 short
  English paraphrases (each at most 30 words) of what it says about the
  monetary-policy outlook (rates, inflation, growth, FX, liquidity).
* `relevant` = false if it says nothing about the policy outlook.
* `speaker` = the official whose views these are (a committee statement: the
  chair if they delivered it, otherwise the committee name).

**expectations** — one per pending task, same `id`:
`{"id", "found": bool, "expected": "hike"|"hold"|"cut", "move_bp", "basis", "outlets": [..]}`

* Use **only** the dated headlines in the task. Count only polls, surveys,
  consensus or market-pricing reports that refer to **that** meeting (the task's
  `date`). A single bank's forecast does not count unless several agree.
* Ignore headlines dated after the meeting.
* `found` = false if the headlines do not establish an expectation; then the
  other fields are "" / [].
* `move_bp` like "+25", "0", "-25". `basis`: one short paraphrase (at most 20
  words), e.g. "Reuters poll: most economists expect a hold". `outlets`: names.

## 3. Rules that override everything

* Never add a fact that is not in the text you were given. When unsure, choose
  `relevant` false or `found` false.
* Do not edit `pending.json` or any other file except the new outbox files.

## 4. Check and push

```bash
python3 scripts/check_outbox.py data/outbox/*.json
```

Fix every reported problem and re-run until it prints `OK`. Then:

```bash
git add data/outbox/*.json
git commit -m "Language step $(date -u +%Y-%m-%d)"
git push origin HEAD:main || (git pull --rebase origin main && git push origin HEAD:main)
```

The push triggers the `Finalize` workflow, which merges the results and
republishes the page.
