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
| M2: worker | ✅ 2026-10-16. `worker` (stdlib Python, 3.9+) plus `ops/worker.plist.template` and `ops/render-worker-plist`. §11 F green: 37 tests against a fake server in `tests/test_worker.py`, 5 against the real server in `tests/test_worker_server.py`. One real video went end to end against a local server. **Not installed yet**: there is no server to poll until M3 |
| **M3: delivery** | **Next.** Summary page, Resend email, Railway deploy, the CNAME, then the worker goes live. Brief below |
| M4, M5, M5b, M6 | Not started. M5b (summaries that stand alone, §10.3) **gates inviting anyone** |

Things a new agent should know:
- **The existing pipeline keeps running until the M6 cutover.** `drain`, the LaunchAgent, the
  weekly digest and the git queue below are still live. Don't break them while building
  `server/` and `worker`.
- **The summarization engine is frozen until M5b:** same prompt, Opus, high effort, flags as in
  `drain`. The worker adds only `--no-session-persistence --output-format json` (D8).
- **The repo is public.** No friend data and no secrets, ever. Secrets live in Railway env vars,
  or in `~/.config/smart_yt_consumer/` (mode 600) on the Mac.
- **Tests:** `python3 -m unittest discover -s tests` for `lib/` and the worker, which are
  stdlib-only. With the server venv's Python instead, the same command also runs the worker
  against the real server. The server: `server/.venv/bin/pytest -c server/pytest.ini
  server/tests` (venv setup in `server/README.md`; Python 3.13, pinned in `.python-version`).
- **Commands the owner runs by hand go in `ops.local.txt`** at the repo root. It is gitignored,
  so it exists only on the owner's Mac. Append the exact command whenever a milestone adds one
  (setup, reset, recovery), with no secrets in it. The owner accepts occasional command-line
  work for bootstrapping and resets, not as a daily chore. Design so that daily use needs none.
- **The owner wants infra steps walked through one at a time,** with an outside check after
  each step (see how M3a was done in `docs/PROPOSAL.md` §10.2).

## M3 brief: delivery

Spec: §5.1 (summary page, email), §8, §10.2 steps 3, 5 and 6, tests §11 H and I. Done when
(§10): §11 H and I are green, and a real email from production reaches Gmail and one other
provider. M2 adds to that: the worker on this Mac completes one real job against production.

**What exists.**
- `server/` (M1). `mail.py` is an outbox with no transport: finished jobs sit at
  `email_status='pending'`. `jobs.public_id` is the capability ID for `/s/<id>`. The choices
  M1 made are listed in `server/README.md`.
- `lib/week.py` renders summary markdown safely (`tests/test_render.py`, I4–I9), but only as a
  whole week page through `lib/page.html`. `/s/<id>` needs a single-summary template derived
  from it (§5.1, "Rendering").
- `worker` (M2) runs against any `SERVER_URL`. Installing it is `ops.local.txt` §5–6.

**Things to get right:**
- **Summary page.** It renders on the server from `summaries.md`, so a template change applies
  to old summaries. Send the headers from I1. The CSP forbids inline script, so "Save as PDF"
  (`window.print()`) needs a static JS file under `server/static/`. Unknown IDs return 404.
  Once `expires_at` passes, the page returns 410 and shows no title (I11). The Railway image
  must include `lib/`.
- **Email.** Use Resend's HTTP API over plain HTTPS (D9), sending as
  `desloppify@notify.ahdimel.com` with `Reply-To: hello@ahdimel.com`. The body is the title,
  the link and "available until <date>", and nothing else (D1, H7). Build the retry loop with
  backoff and the reset of stale `sending` rows that `server/README.md` says M3 owes. On a 4xx,
  mark the email failed and don't retry (H5).
- **Railway.** Create a new service with a volume, and set `DB_PATH` on the volume. Env vars:
  `WORKER_TOKEN`, `RESEND_API_KEY`, `PUBLIC_ORIGIN=https://desloppify.ahdimel.com` and
  `CLIENT_IP_HEADER`. Find out which header Railway's edge actually sets rather than guessing,
  because clients can forge any other. Keep uvicorn's `--no-access-log`. Work out how the
  owner runs `server.cli invite` against the production DB, and fill in `ops.local.txt` §2.
- **Domain and key.** Follow §10.2 step 3: the CNAME plus Railway's verify TXT, checked against
  the three resolvers named in `CLAUDE.md`. Then step 5: a send-only Resend key scoped to
  `notify.`, which the owner puts straight into Railway and which never touches the Mac's disk.
  Walk the owner through both one step at a time, with a check after each.
- **The worker goes live.** Do this once `https://desloppify.ahdimel.com/healthz` answers. The
  owner creates `~/.config/smart_yt_consumer/env` (`ops.local.txt` §5), which generates the
  token on the Mac. The same token then has to reach Railway's `WORKER_TOKEN` without being
  echoed or passing through the clipboard: design that step. Then install the LaunchAgent
  (§6). **Ask before loading it.** `drain` keeps running alongside until M6.
- **Railway's HTTP logs record paths.** `/s/<public_id>` is a capability URL, like `/u/<token>`.
  Note it for M5's log audit, as `server/README.md` already does for `/u/`.
- **Don't invite anyone.** M5b gates that.

**What M2 learned, for whoever touches the worker:**
- An idle worker logs nothing. To see that the timer fires, read `runs` and `last exit code`
  in `launchctl print gui/$(id -u)/com.ahdimel.smartytconsumer.worker`.
- An unreachable server is logged once per outage (the flag file is `.work/.unreachable`), not
  once a minute. After `rate_limited`, or after a report the server didn't acknowledge, the run
  stops and the next one starts 60 s later.
- The real run: a 3-minute video took 108 s and used 22.6k cache-write, 4.9k cache-read and
  5.3k output tokens, $0.37 API-equivalent. The summary closely matched drain's for the same
  video.
- `drain`'s `--disallowed-tools` list and `vsum`'s `--sub-langs` and `--extractor-args` are
  copied into `worker`. A test fails if they drift apart. When M6 retires `drain`, move the
  canonical copy into `worker`.

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
