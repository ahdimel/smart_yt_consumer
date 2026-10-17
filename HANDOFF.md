# Handoff

State of the project as of 2026-10-17, for whoever picks it up next. `README.md` explains the
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
| M1: server core | ✅ 2026-10-16. `server/`: FastAPI + SQLite, invites, cookie/bearer auth, URL validation, quotas, cache + coalescing, admin view, pause, worker protocol. 154 tests (§11 A–E, G) green; smoke-tested under uvicorn. Deployed in M3. Choices the proposal left open are listed in `server/README.md` |
| M2: worker | ✅ 2026-10-16. `worker` (stdlib Python, 3.9+) plus `ops/worker.plist.template` and `ops/render-worker-plist`. §11 F green: 37 tests against a fake server in `tests/test_worker.py`, 5 against the real server in `tests/test_worker_server.py`. Installed and live against production since M3 |
| M3: delivery | ✅ 2026-10-16. `/s/<id>` summary page with Save as PDF, Resend email with a retry loop, Railway deploy at `https://desloppify.ahdimel.com`. §11 H, I green (196 server tests). Email from production passes SPF, DKIM and DMARC at Gmail and Proton. The worker LaunchAgent completed one real job end to end: submit → claim → summary (181 s, $0.54) → email → page. Its logs and Railway's hold no URL, video ID or title |
| M4: intake and intro page | ✅ 2026-10-17, **except two open items** below. `/share` (Android share target), `/add` (bookmarklet), the manifest and icons, a "Paste and summarize" button, `/welcome` and `/about`; refused browser forms answer with pages. §11 J, M green (251 server tests). Verified against production from Firefox on the Mac (paste box, bookmarklet: new video and cache hit), and on an iPhone 15 Pro, iOS 26 (paste button in Safari and Firefox, sign-in in Chrome, the Home Screen icon, email → summary page → timestamp chips into the YouTube app). The HTTP log showed no URL, video ID or title on any of these paths |
| **M5: retention and privacy audit** | **Next.** Brief below |
| M5b, M6 | Not started. M5b (summaries that stand alone, §10.3) **gates inviting anyone**. Only the owner has a production login |

**Open from M4** (do these before M6, ideally in the next deploy):
1. **Android is unverified on a device.** The owner has no Android phone yet. The share target is
   built and tested, but §12's question (does Chrome attach the `SameSite=Lax` cookie to an
   OS-started share POST, and with which `Sec-Fetch-Site`?) is unanswered. Every `/share` writes
   one app-log line, `share site=<…> origin=<…> cookie=<yes|no>`, which answers it. Steps are in
   `ops.local.txt` §12. `cookie=no` or `refused cross_origin` means the fallback: a service
   worker at `/sw.js` that catches the share POST and re-posts it same-origin.
2. **The intro copy is Claude's draft.** The owner rewrites `server/intro.py` in their own voice
   (its docstring explains the `$` placeholders). Production runs `be329a8`; the commits after it
   (`/favicon.ico`, the "each browser signs in on its own" line, iPhone → Home Screen) go out with
   the rewrite, in one deploy.
3. Minor: on the owner's iPhone the icon showed white bars on **black**, not the blue square. Most
   likely iOS's Dark/Tinted icon appearance recolouring it; unconfirmed.

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

## M5 brief: retention purge and privacy audit

Spec: §6 (privacy design), §11 K, the M5 row of §10, and "Railway request logs" in §6's table.
Done when (§10): §11 K is green, and a manual pass over Railway's logs shows no content.

**What exists.**
- **Retention is enforced at read time, but nothing is ever deleted.** `/s/<id>` returns 410 once
  `min(summaries.expires_at, jobs.finished_at + 30 days)` has passed, and the cache lookup in
  `intake.submit` skips expired rows. But `summaries` rows and `jobs.video_id` stay in the
  database forever. M5 adds the purge (K1, K2). `test_purged_is_410` in
  `server/tests/test_summary_page.py` already simulates its effect.
- Usage columns live on `jobs` and must survive the purge (§5.1). The admin view never selects
  content columns (G3); M5's admin-response audit re-runs that over every admin route after a
  purge.
- **The app's own log** holds only these lines: `started mailer=`, `submit job= user= status=`,
  `claim job= attempt=`, `complete|fail job=` (`rejected=`), `mail job= attempt= outcome=
  http=`, `mail job= error=`, `mail loop error=`, `invite|revoke|reissue user=`,
  `paused|resumed`, `share site= origin= cookie=` and `refused cross_origin site= origin=
  cookie=` (M4: categories only, never header values).
- **`ops/audit-http-log`** reads `railway logs --http --json`, masks `/u/<token>` and
  `/s/<id>`, and flags any path or query that could carry a URL, ID or title. Through M4 it
  flagged nothing. Railway's HTTP log records `path`, `clientUa` and `srcIp`, and no Referer
  or body.
- The Mac worker removes `.work/<job>/` at job end (F1–F3), and its log has no content (F15).

**Things to get right:**
- **The purge (K1, K2).** Delete `summaries` whose `expires_at <= now`, and null `jobs.video_id`
  once a job's 30 days are up. Only touch `done` and `failed` jobs: a `queued` job can be older
  than 30 days if the Mac was off, and the worker needs its video ID. Run it in one `BEGIN
  IMMEDIATE` transaction so it is safe beside a submit (K2), and from a loop in the app, the way
  `mail_loop` runs. Admin totals and every usage column must be unchanged after it (K1).
- **The owner can read capability URLs in Railway's HTTP log.** This is the biggest finding for
  M5. Every summary view logs `/s/<public_id>`, and opening that path shows the friend's
  summary. So "the owner never sees content" holds only while the owner doesn't open a path from
  their own log. The same goes for `/u/<token>`, which logs anyone in as that friend. Options:
  move the capability into a `#fragment` (`/s#<id>`, with a static script fetching it by POST,
  like `/add`), shorten Railway's log retention, or accept it and say so on `/about`. **This is
  the owner's call: ask before building.**
- **Other places content lives** (§6's table): Resend's dashboard keeps titles (D1). Check
  Resend's retention for this plan, and whether logs can be shortened. Browsers keep `/u/<token>`
  in their history wherever the invite link was opened (seen in M4). The friend's own inbox and
  PDFs are theirs.
- **K3** captures app logs over a full submit → claim → complete → email cycle, and greps for
  the canary title, the video ID and `youtube`. **K4**: nothing under the repo is written outside
  gitignored paths. **K5** was done in M0.
- **Scanners arrived within hours** of the hostname going live: phishing-kit paths and
  `/.git/HEAD`, from Android-like user-agents. All 404. Expect them in any manual log pass;
  they're noise, not friends.
- **Don't invite anyone.** M5b still gates that.

**What M3 and M4 learned, for whoever touches the server:**
- **Try every form and route from a real browser against production.** With `Referrer-Policy:
  no-referrer`, browsers send `Origin: null` on their own same-origin POSTs, which test clients
  don't. `same_origin()` trusts `Sec-Fetch-Site: same-origin` for that (M3). In M4, Firefox on
  macOS and iOS and Safari on iOS 26 all passed the paste box and `/add`'s `fetch` this way.
- **iOS:** each browser app has its own cookies (Safari, Chrome and Firefox on one phone sign in
  separately). On iOS 26, Safari's **Add to Home Screen** carries the login into the icon.
  Safari on iOS 26 reports `iPhone OS 18_7` in its User-Agent (frozen), so match on `iPhone`,
  never on a version.
- **No iOS Shortcut.** The owner judged both token-paste designs too complex for non-technical
  friends (2026-10-16). iPhone users get "Paste and summarize" plus a Home Screen icon. The
  bearer API (`POST /api/requests` with `Authorization: Bearer`) stays and is tested (J6).
  `paste.js` sends clipboard text only when it names a YouTube host.
- **Proton files the summary email under "Newsletters".** `/welcome` says so. Proton's rspamd
  also rejects app mail to an `@ahdimel.com` mailbox when `Reply-To` equals `To` and the body
  links to `desloppify.`; `mail.py` drops Reply-To in that case.
- **Railway:** no `railway.json` for new services. The healthcheck was set through `railway api`.
  The edge overwrites `X-Real-IP`. `railway ssh` needs `railway ssh keys add` once. FastAPI's
  `@app.get` doesn't answer HEAD. Deploy only with `railway up` from a clean tree, and ask
  first.
- **Failure emails carry no title**, because the worker reports none. That fix touches the
  worker, so it waits for M5b.

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
