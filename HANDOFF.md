# Handoff

State of the project as of 2026-10-16, for whoever picks it up next. `README.md` explains the
method and setup; `CLAUDE.md` holds the working rules for agents. This file covers what is true
right now, what is fragile, and what is tied to one person's machine.

## Now: turning this into a service for friends

The plan is **`docs/PROPOSAL.md`**: decisions, architecture, milestones (§10) and the validation
test matrix (§11). The owner settled every decision in it through an interview on 2026-10-15/16.
Build against it; don't reopen the decisions without asking.

| Milestone | State |
|---|---|
| M0: measure and fix | ✅ XSS fix in `lib/week.py` + `tests/test_render.py` (17 tests). The overhead A/B is in `docs/m0-ab.md`; adoption shelved to M5b |
| M3a: domain and email | ✅ except the Railway CNAME (comes with M3). `ahdimel.com` on Namecheap; Proton for people; Resend on `notify.ahdimel.com` for apps; DMARC `quarantine`. See "DNS & email" in `CLAUDE.md` |
| M1: server core | ✅ 2026-10-16. `server/`: FastAPI + SQLite, invites, cookie/bearer auth, URL validation, quotas, cache + coalescing, admin view, pause, worker protocol. 154 tests (§11 A–E, G) green; smoke-tested under uvicorn. Local only. Choices the proposal left open are listed in `server/README.md` |
| **M2: worker** | **Next.** Mac-side `worker` against the M1 protocol (`claim` → `complete`/`fail` with `lease_id`). Tests §11 F |
| M3, M4, M5, M5b, M6 | Not started. M5b (summaries that stand alone, §10.3) **gates inviting anyone** |

Things a new agent should know:
- **The existing pipeline keeps running until the M6 cutover.** `drain`, the LaunchAgent, the
  weekly digest and the git queue below are still live. Don't break them while building
  `server/` and `worker`.
- **The summarization engine is frozen until M5b:** same prompt, Opus, high effort, flags as in
  `drain`. The worker adds only `--no-session-persistence --output-format json` (D8).
- **The repo is public.** No friend data and no secrets, ever. Secrets live in Railway env vars,
  or in `~/.config/smart_yt_consumer/` (mode 600) on the Mac.
- **Tests:** `python3 -m unittest discover -s tests` for `lib/`, which is stdlib-only. The
  server: `server/.venv/bin/pytest -c server/pytest.ini server/tests` (venv setup in
  `server/README.md`; Python 3.13, pinned in `.python-version`).
- **Commands the owner runs by hand go in `ops.local.txt`** at the repo root. It is gitignored,
  so it exists only on the owner's Mac. Append the exact command whenever a milestone adds one
  (setup, reset, recovery), with no secrets in it. The owner accepts occasional command-line
  work for bootstrapping and resets, not as a daily chore. Design so that daily use needs none.
- **The owner wants infra steps walked through one at a time,** with an outside check after
  each step (see how M3a was done in `docs/PROPOSAL.md` §10.2).

## M2 brief: the Mac worker

Spec: proposal §5.3, error codes §5.5, tests §11 F. The server side is done and tested, so build
against it rather than against the proposal's prose. Where they differ, the server is right.

**Protocol** (see `server/protocol.py`; `server/smoke.sh` exercises it with curl). All calls go
over HTTPS with `Authorization: Bearer $WORKER_TOKEN`.
- `POST /worker/claim` with body `{"version": "<worker version>"}`. The answer is **204** when
  there is nothing to do: queue empty, paused, or over the token ceiling. Otherwise **200**
  `{job_id, lease_id, lease_until, attempt, video_id, url, max_minutes}`. `url` is already
  canonical; pass exactly that to yt-dlp.
- `POST /worker/jobs/{job_id}/complete` with body `{lease_id, md, usage, cost_usd, model}`.
  `usage` is `claude -p`'s JSON `usage` object, passed through as is; the server maps
  `cache_creation_input_tokens` and `cache_read_input_tokens` itself. Answers: **200** done,
  including a replay of the same lease. **409**: the lease is dead (expired and re-leased, or
  the job already failed), so drop the result. **422**: the front matter is invalid, the job
  stays leased, so report `fail` with `invalid_output`. **413**: over 1 MB.
- `POST /worker/jobs/{job_id}/fail` with body `{lease_id, error_code, usage, cost_usd}`.
  `error_code` must be one of the keys in `server/codes.py`. The server decides retries and
  backoff from the code. The worker never retries a job itself; it reports and moves on.
- `md` must start with `---` front matter that has a `title:`. Strip a wrapping code fence
  first (F8, as `lib/clean.py` does). The server does not strip it.

**Things to get right:**
- **The summarize call is D8, not §11 F13's `--tools ""`.** F13 was written when the lean flags
  were planned. M0 shelved them (`docs/m0-ab.md`). Use `drain`'s `--disallowed-tools` list plus
  `--model opus --effort high --no-session-persistence --output-format json`, prompt first, run
  from the repo root, bundle on stdin, capped at 600 s. Change F13 to assert that.
- **Fetch in two steps.** `vsum` downloads metadata, subtitles and comments in one yt-dlp call.
  §5.3 wants duration, live status and captions checked *before* spending more. So: metadata
  first (`--skip-download --dump-json` or `--write-info-json`), then classify `too_long`,
  `live_or_upcoming`, `no_captions` and so on; only then fetch subtitles and comments and run
  `lib/bundle.py`. Reuse `vsum`'s subtitle language list and `--extractor-args`. The comments
  there explain hard-won rate-limit fixes.
- **Everything per job goes in `.work/<job_id>/`** (gitignored), including `VSUM_CACHE`. A
  `trap` removes it on every exit path. `result.json` survives only until `complete` is
  acknowledged (F11). Don't write to `.cache/` or `out/`; `drain` still owns those.
- **The log holds job IDs, codes and token counts only.** No URL, video ID or title (F15).
- **Don't disturb `drain`.** It stays live until M6, and both may run at once. Give the worker
  LaunchAgent its own label (`com.ahdimel.smartytconsumer.worker`); its plist template goes in
  `ops/worker.plist.template` (§9). Resolve `claude` at install time instead of hardcoding the
  nvm path (§9).
- **Secrets:** `WORKER_TOKEN` and the server URL go in `~/.config/smart_yt_consumer/env`, mode
  600 (§5.3). Generate the token on the Mac and have the owner do it via `read -rs`-style steps.
  Add the commands to `ops.local.txt`.
- **Done when:** §11 F green with stub `yt-dlp` and `claude` first on `PATH`, and one real video
  end to end against a local server (`server/smoke.sh` shows how to start one). There is no
  Railway yet; that is M3.

## The existing pipeline (state as of 2026-10-07, still running)

- **Working and unattended:** queue → fetch → summarize → week page → commit → push. The
  LaunchAgent has run every 15 minutes while the Mac is awake since at least 2026-09-26, and
  came back by itself after a reboot on 2026-09-27.
- **Manual:** publishing the artifacts. The owner chose this on 2026-10-03 over moving the pages
  to GitHub Pages.
- **Output so far:** 41 summaries across three weeks (2026-W38: 24, W39: 11, W40: 6). Nothing
  has been queued for W41.
- **Health on 2026-10-07:** `./status` reports the timer loaded, queue empty, and all weeks
  published and current.
- **Artifacts:** the URLs are in `out/<week>/meta.json` and `out/index.meta.json`. The W40
  artifact and the index are shared as "anyone with the link"; the sharing state of W38 and W39
  was not checked.
- **The GitHub repo is public.** Every summary, every week page and every artifact URL in `out/`
  is readable by anyone.

## Why publishing is manual

The Artifact tool exists only when `claude` is started from inside a Claude Code session. This
was tested on 2026-10-03: `claude -p` in a bare environment reported no Artifact tool, and the
same command launched from a session's shell reported having it. Which part of the session
environment makes the difference was not isolated.

Under launchd the publish step therefore failed on every run, each time spending a capped
`claude -p` session to find that out. `drain` now checks for the `CLAUDECODE` environment
variable after pushing; if it is absent, it regenerates the index page, logs one line and exits.

`./publish` was last run on 2026-09-25, for W38 and W39. On 2026-10-03 the W40 artifact and the
index were published directly with the Artifact tool from a session, so `./publish` has not been
exercised since the `published_sha` check was added to `drain` and `status`.

## Tied to one machine or one person

Anything that makes this usable by other people has to deal with these.

- **macOS only.** The scripts use `launchctl`, BSD `date -j` and `date -v`, and `perl -e alarm`
  standing in for `timeout`.
- **Hardcoded paths.** `drain` and `publish` prepend
  `$HOME/.nvm/versions/node/v24.15.0/bin` to `PATH` to find `claude`; a Node upgrade breaks
  this silently until the next run logs "claude CLI not on PATH". The LaunchAgent label and
  `status` both hardcode `com.ahdimel.smartytconsumer`, and the page footer links to
  `github.com/ahdimel/smart_yt_consumer`.
- **The LaunchAgent plist is not in the repo.** Its contents are reproduced in `README.md`.
- **The queue is the git repo.** Queuing a video means push access to it. There is no other
  intake, no per-user separation, and no rate limit.
- **One digest for everyone.** Weeks, pages and artifacts are global to the repo.
- **Summaries run on the owner's Claude login.** Each video is one `claude -p` call, capped at
  600 seconds, plus one or more calls per publish.
- **Fetching needs a residential IP.** YouTube bot-checks datacenter addresses, so the fetch
  cannot simply move to a cloud host.
- **Artifacts belong to the owner's claude.ai account**, and only a session on that account can
  update them.

## Known gaps

- **No retry limit.** A URL whose fetch or summary fails stays in `queue/` and is retried every
  15 minutes indefinitely. There is no dead-letter folder and no notification.
- **No alerting.** Failures appear only in `~/Library/Logs/smart_yt_consumer/drain.log` and in
  `./status`, which shows the last three from the past two days.
- **The log is never rotated**, and `.cache/` (about 150 MB) is never pruned.
- **Week assignment uses the processing date**, not the queue date, so a URL queued on Sunday
  and drained on Monday lands in the new week.
- **A video is deduplicated only within its week.** Re-queuing one in a later week summarizes
  it again.
- **`vsum` and `drain` disagree.** Run directly, `vsum` writes `out/<date>-<id>.md` with tools
  enabled and without the clean step; `drain` writes `out/<week>/<id>.md` with tools disabled.
  Only the second is picked up by the week page.
- **`out/<week>/.publish.log` is tracked in git**, while `out/.index.log` is ignored. The
  tracked logs hold model output from publish attempts and are overwritten on each run.
- **`examples/` is in the old format**, without front matter, and holds four of the five videos
  in the README table.
- **No tests.** Correctness so far has been checked by reading outputs and the drain log.

## Things already learned the hard way

- Do not trust `claude -p` exit codes. It exits 0 whether or not it did the work. Check the
  artifact, `meta.json` or the output file.
- In `claude -p`, the prompt must come before `--disallowed-tools`. The flag is variadic and
  otherwise swallows the prompt.
- Summarize with tools disabled. With tools on, the agent writes files itself and prints
  nothing, so the redirect captures an empty file.
- Ask `yt-dlp` only for the subtitle tracks the flattener reads. `en.*` also matches
  auto-translated tracks, and enough of those in a batch trips YouTube's rate limiter.
- Keep the repo out of `~/Documents`, `~/Desktop` and `~/Downloads`; LaunchAgents cannot read
  them.
- Word-compression ratio does not measure padding. The fluff fraction does. See `README.md`.
