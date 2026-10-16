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
| M3a: domain and email | ✅ 2026-10-16, including the Railway CNAME (done in M3). `ahdimel.com` on Namecheap; Proton for people; Resend on `notify.ahdimel.com` for apps; DMARC `quarantine`. See "DNS & email" in `CLAUDE.md` |
| M1: server core | ✅ 2026-10-16. `server/`: FastAPI + SQLite, invites, cookie/bearer auth, URL validation, quotas, cache + coalescing, admin view, pause, worker protocol. 154 tests (§11 A–E, G) green; smoke-tested under uvicorn. Local only. Choices the proposal left open are listed in `server/README.md` |
| M2: worker | ✅ 2026-10-16. `worker` (stdlib Python, 3.9+) plus `ops/worker.plist.template` and `ops/render-worker-plist`. §11 F green: 37 tests against a fake server in `tests/test_worker.py`, 5 against the real server in `tests/test_worker_server.py`. Installed and live against production since M3 |
| M3: delivery | ✅ 2026-10-16. `/s/<id>` summary page with Save as PDF, Resend email with a retry loop, Railway deploy at `https://desloppify.ahdimel.com`. §11 H, I green (196 server tests). Email from production passes SPF, DKIM and DMARC at Gmail and Proton. The worker LaunchAgent completed one real job end to end: submit → claim → summary (181 s, $0.54) → email → page. Its logs and Railway's hold no URL, video ID or title |
| **M4: intake and intro page** | **Next.** Brief below |
| M5, M5b, M6 | Not started. M5b (summaries that stand alone, §10.3) **gates inviting anyone**. Only the owner has a production login |

Things a new agent should know:
- **The existing pipeline keeps running until the M6 cutover.** `drain`, its LaunchAgent, the
  weekly digest and the git queue below are still live, alongside the worker's LaunchAgent
  (`com.ahdimel.smartytconsumer.worker`). Don't break them while building `server/` and `worker`.
- **Production** is Railway project `desloppify`, service `server`, with a volume at `/data`.
  This directory is linked to it with `railway link` (stored in `~/.railway`, not the repo). The
  repo holds no Railway IDs: keep it that way. Deploy with `railway up --service server --ci`
  from a clean tree (`ops.local.txt` §10). Deploys never follow a git push, because drain pushes
  every 15 minutes. **Ask the owner before every deploy.** `server.cli` runs inside the service
  through `railway ssh` (§2). Secrets (`WORKER_TOKEN`, `RESEND_API_KEY`) live in Railway; don't
  print them with `railway variable list --kv`.
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

## M4 brief: intake modalities and the intro page

Spec: §5.2 (intake), §5.4 (intro page), §2 "Intro page" and "Extras", tests §11 J and M.
Done when (§10): manually verified on one Android, one iPhone and one desktop, and §11 J and M
are green. The owner rewrites the intro copy in their own voice, so leave time for that round.

**What exists.**
- Production at `https://desloppify.ahdimel.com` (M3), with the owner as the only user (admin).
  `GET /welcome` and `/about` are placeholders; `/` is the M1 paste box and a bare job list.
  `POST /api/requests` already takes JSON `{url}`, form `url`/`text`, and `text/plain`, by
  cookie or by bearer (J6's server side).
- `server/pages.py` builds HTML with `html.escape` and no template engine. The CSP allows
  script and style only from `'self'`, so every script is a file under `server/static/`. Add it
  to `STATIC_TYPES` in `app.py`, which also serves its content type. `summary.js` is the
  example.
- `auth.same_origin()` guards every cookie POST. See below for what it learned in M3.

**Things to get right:**
- **`POST /share` (Android share target).** It accepts `url`, `text` (the YouTube app puts the
  link there) or only `title` (J1–J3). It is a cookie POST that the OS starts, not a page, so
  check which `Sec-Fetch-Site` and `Origin` Chrome actually sends, and whether the `SameSite=Lax`
  cookie comes along (§12). Verify on a real device before trusting a test. The fallback is a
  service worker that catches the share and re-posts it same-origin.
- **`/add` (bookmarklet).** The URL travels in `#fragment`, which never reaches the server. The
  page's script (a static file) reads `location.hash` and POSTs it. J5 asserts on the request
  log that the server never saw the URL in a path or query, and J7 that intake routes refuse GET
  with a query string (405).
- **The iOS Shortcut** posts JSON with `Authorization: Bearer <token>`. The friend pastes their
  token once. The intro page must explain this without showing the token anywhere it could leak
  (no query strings, nothing logged).
- **`/manifest.webmanifest`** declares `share_target` with POST and form encoding (J4). Icons
  are static files too.
- **`/welcome` and `/about` (§5.4).** Claude drafts from §5.4's outline; **the owner rewrites the
  copy.** `/welcome` puts the setup block matching the User-Agent first and collapses the others
  (M5). Limits come from the user's row, not hardcoded numbers (M6). With no cookie, both return
  the bare "Private, invite-only." page (M3, M4).
- **Browser forms should show errors as a page, not JSON.** A refused paste-box POST (403, 401,
  429) currently shows the raw JSON body. The redirect-with-message path in `submit` covers
  quota and invalid URLs only.
- **Don't invite anyone.** M5b gates that. Test devices use the owner's own login, or a
  throwaway user that is revoked afterwards.

**What M3 learned, for whoever touches the server:**
- **`Referrer-Policy: no-referrer` makes browsers send `Origin: null`** on their own same-origin
  form POSTs (Fetch standard). M1's check refused that, so every browser form returned 403 in
  production until `same_origin()` learned to trust `Sec-Fetch-Site: same-origin`. The test
  client sends a real Origin, so tests alone didn't catch it. Try every new form from a real
  browser against production.
- **Proton's rspamd rejects app mail to an `@ahdimel.com` mailbox** when `Reply-To` equals `To`
  and the body links to the young `desloppify.` hostname; either alone passes. `mail.py` drops
  Reply-To when it equals the recipient. A friend on `@proton.me` is untested.
- **Proton files the summary email under "Newsletters"** (seen on the first production job).
  It arrives, but in a category the reader may not check. The intro page's setup steps should
  say where to look, and suggest adding the sender to contacts (§10.2 step 6).
- **Railway:** new services can't use `railway.json` (deprecated; its replacement is
  `.railway/railway.ts`). The healthcheck and restart policy were set once through `railway api`.
  The edge overwrites `X-Real-IP` (checked by forgery, `server/README.md`). `railway ssh` needs
  the key registered with a bare `railway ssh keys add`. FastAPI's `@app.get` doesn't answer
  HEAD, so `/healthz` declares it for `curl -I`.
- **Failure emails carry no title**, because the worker reports none (`server/README.md`).
  Fixing that touches the worker, so it waits for M5b.
- **Railway's HTTP log records paths**, including `/u/<token>` and `/s/<public_id>`. The app's
  own log holds job IDs, codes and outcomes only. M5's audit should start from this.

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
