# Proposal: smart_yt_consumer as a service for friends

Status: **decisions settled**, 2026-10-15. Written to be executed against milestone by
milestone. `README.md` and `HANDOFF.md` describe the system as it is today; this document
describes what it becomes.

## 1. Goals

1. **One simple external entry point** through which friends submit YouTube URLs.
2. **Secure entry**: nobody without an invite can submit or read anything.
3. **Runs on the owner's Mac and Claude subscription.** Fetching needs a residential IP;
   summarizing uses the owner's `claude` login.
4. **The owner sees usage, not content**: request counts and token usage per user, so the
   subscription is protected from abuse — but never which videos anyone asked for.
5. **HTML summaries delivered to each friend**, on a queue that drains on a timer.

## 2. Decisions

Settled with the owner on 2026-10-15:

| Question | Decision |
|---|---|
| Delivery | Short HTML email (**title + link only**) + the full summary on a hosted page |
| Auth | Personal invite link per friend; revocable; the link is the login |
| Billing | Owner's subscription via `claude -p` |
| Privacy | "Out of sight": content never in logs, git, admin views or transcript stores; purged after retention |
| Domain | **`ahdimel.com`**, bought 2026-10-15 on Namecheap with WHOIS privacy and auto-renew. A personal domain shared by lightweight projects, each on its own subdomain. This app: **`desloppify.ahdimel.com`** |
| Email | App mail: Resend from the subdomain **`notify.ahdimel.com`**, shared by every project; this app sends as `desloppify@notify.ahdimel.com`. People mail: `hello@ahdimel.com` on Proton Mail Plus. Set up and verified 2026-10-16 (§10.2) |
| Scale & limits | ≤10 friends. Per user 5/day, 20/week, videos ≤ 3h. Global 40/day. All per-user adjustable |
| Owner's digest | Owner becomes a user like everyone else. Weekly artifact digest and git queue are retired |
| Extras | Status + history page; shared summary cache; share-sheet intake on Android and a bookmarklet on desktop. iPhone uses a "Paste and summarize" button instead of a share-sheet Shortcut (changed 2026-10-16, §5.2) |
| Intro page | Explains the tool to invitees; shown on first visit and at `/about`. Strangers see one line (§5.4) |

Design details, all accepted:

| # | Decision | Why |
|---|---|---|
| D1 | The email carries the **title and a link only**: no verdict, no prose | Resend's dashboard keeps sent mail; it then holds titles and nothing else |
| D2 | Retention **30 days** for summaries, the cache and job↔video links. Summary pages have a "Save as PDF" button | 7 days was considered, but with title-only email the page is the only copy |
| D3 | Summary pages are unguessable capability URLs, forwardable | A friend can open the email link on any device without logging in |
| D4 | Input naming two different videos is rejected ("one at a time") | Ambiguity is worse than a retry |
| D5 | Worker polls every 60 s, not 15 min — a poll is one cheap HTTPS call | Latency drops from ~8 min average to ~30 s |
| D6 | Mac sleeps normally; jobs wait, and the status page says so | No change to how the laptop is used |
| D7 | Repo stays public. No friend data ever touches git, which tests enforce | — |
| D8 | **Summarize exactly as production does today** (same prompt and flags, run from the repo root), with model and effort pinned explicitly (`--model opus --effort high`), plus `--no-session-persistence --output-format json` | Production silently inherited `opus` from user settings; pinning keeps the worker from depending on them. The engine itself is revisited in M5b |
| D9 | Server stack: Python 3.13 (pinned in `.python-version`), FastAPI, SQLite on a Railway volume, Resend over plain HTTPS | Same shape as REI, minus Postgres and Alembic. 3.12 was REI's version, not a requirement; 3.13 is what this Mac has (changed 2026-10-16) |

## 3. What changes, in one picture

```
 friend's phone / laptop                     Railway (app.<domain>)                 owner's Mac
 ───────────────────────                     ──────────────────────                 ───────────
 paste box ─────────┐                        ┌──────────────────────┐
 Android share ─────┤  POST (cookie/bearer)  │ intake: validate URL │
 iPhone paste btn ──┼──────────────────────► │ auth · quota · cache │
 desktop bookmarklet┘                        │ SQLite: users, jobs, │   POST /worker/claim
                                             │   summaries, usage   │ ◄──────────────── worker (60 s)
                                             │                      │   job: video id     │ yt-dlp
                                             │                      │ ──────────────────► │ bundle
                                             │                      │                     │ claude -p
                                             │                      │   POST complete     │ (json usage)
                                             │ render · store ·     │ ◄────────────────── │ rm -rf job dir
 email: title + link ◄───────────────────────│ email · history page │
 /s/<id> summary page ◄──────────────────────│ admin: counts+tokens │
                                             └──────────────────────┘
```

The Mac only makes **outbound** HTTPS calls. Nothing at home is exposed: no tunnel, no port
forward. If the Mac is asleep, jobs wait on Railway and the friend's status page says so.

## 4. Suggestions folded into this plan

Beyond the stated goals, these came out of reading the code and probing the CLI:

1. **Strip Claude Code's overhead from every summary (M0, measured, then shelved until M5b).**
   Each `claude -p` call carries
   Claude Code's own system prompt, tool definitions and the repo's `CLAUDE.md`. With
   `--tools "" --system-prompt "<short>" --setting-sources "" --strict-mcp-config
   --no-session-persistence` the call carries only the prompt and the bundle. **Measured in the
   M0 A/B (`docs/m0-ab.md`):** input tokens fell 52% and API-equivalent cost per summary 29%
   ($0.65 → $0.46). Thinking-heavy output dominates the rest. Quality held or improved on every
   automatic check.
2. **Stop the transcript leak.** Headless runs persist sessions: there are 56 files under
   `~/.claude/projects/-Users-ahdimel-code-smart-yt-consumer/`, each with a full video transcript
   and summary. `--no-session-persistence` stops this; without it "out of sight" is false.
3. **Fix an XSS hole before anything is hosted.** `lib/week.py:inline()` turns `[x](url)` into
   `<a href="url">` with no scheme check, after escaping with `quote=False`. So
   `[x](javascript:…)` and `[x](" onmouseover="…)` both produce live script. The model's input
   includes YouTube comments, which anyone in the world can write. Fix: escape quotes, allow
   only `https?:` links, and add a CSP on every page.
4. **Pull, don't push.** The worker polls Railway, so the Mac needs no inbound exposure.
5. **Coalesce identical in-flight requests.** If two friends submit the same uncached video, it
   is summarized once and both are notified.
6. **Retire publishing entirely.** With the owner as a user, the Artifact publishing machinery
   (`publish`, `meta.json`, `published_sha`, `index_page.py`) goes away, and with it the manual
   step that never worked headless. The history page, grouped by ISO week, replaces the weekly
   digest.
7. **Keep content out of URLs.** Railway's request logs record paths. Every route that carries a
   video URL is a POST body, or a `#fragment`, which browsers never send to the server.

## 5. Components

### 5.1 Railway app (`server/`)

**Data model** (SQLite, one file on a Railway volume):

```
users      id, name, email, token_hash, is_admin, daily_limit, weekly_limit, max_minutes,
           created_at, welcomed_at, revoked_at
jobs       id, public_id (128-bit, URL-safe), user_id, video_id (nulled at retention),
           status [queued|running|done|failed], cache_hit, coalesced_with,
           attempts, not_before, lease_until, error_code,
           input_tokens, cache_write_tokens, cache_read_tokens, output_tokens, cost_usd, model,
           email_status [pending|sent|failed], created_at, finished_at
summaries  video_id (pk), md, title, verdict, created_at, expires_at       -- also the cache
settings   paused, global_daily_limit, global_daily_token_ceiling
worker     last_seen, version
```

Usage columns live on `jobs` and outlive retention. Content (`summaries`, `jobs.video_id`)
does not.

**Routes**

| Route | Auth | Purpose |
|---|---|---|
| `GET /u/{token}` | token | Set cookie, 303 → `/welcome` on first visit, otherwise `/`. The token never appears in a URL again |
| `GET /` | cookie | Paste box, quota remaining, queue, history grouped by week, worker status. Without a cookie: one line, "Private, invite-only." |
| `GET /welcome` | cookie | Intro page + setup steps for the friend's platform; sets `welcomed_at` |
| `GET /about` | cookie | Intro page alone |
| `POST /api/requests` | cookie or `Authorization: Bearer` | Submit `{url}` or form `url`/`text`. Returns job state |
| `POST /share` | cookie | Android PWA share target (form-encoded `title`, `text`, `url`) |
| `GET /add` | cookie | Bookmarklet landing: reads `#<url>` client-side, POSTs it |
| `GET /s/{public_id}` | capability | Rendered summary. 404 unknown, 410 expired |
| `GET /admin` | admin cookie | Users, usage, invites, limits, pause switch. No content |
| `POST /admin/...` | admin cookie | Create/revoke invite, edit limits, pause/resume |
| `POST /worker/claim` | worker token | Lease the next job, or 204 |
| `POST /worker/jobs/{id}/complete` | worker token | Summary markdown + usage |
| `POST /worker/jobs/{id}/fail` | worker token | Error code, retryable flag, usage so far |
| `GET /healthz` | none | Liveness only |

**Rendering** happens on the server, from markdown, using the (fixed) `lib/week.py` renderer
and a single-summary template derived from `lib/page.html`. Template changes therefore apply
to old summaries without re-running anything.

**Email** is sent by the server after `complete` or a final `fail`, via Resend's HTTP API from
`desloppify@notify.ahdimel.com` with `Reply-To: hello@ahdimel.com`, so a friend's reply lands in
the owner's Proton inbox instead of bouncing off a send-only address. HTML plus a plain-text part. Content: the video title, a "Read the
summary" link, and "available until <date>". No verdict and no prose (D1). Failure emails carry
the title and the plain-language reason. Failed sends are retried by a background loop; a
summary never sends two emails.

**Summary page** (`/s/<public_id>`): the rendered summary, with a "Save as PDF" button that
calls `window.print()` against a print stylesheet. Once the 30 days are up, the page returns
410 with a line explaining it expired.

### 5.2 Intake modalities

All four modalities end up at the same API call.

| Platform | Mechanism | Setup for the friend |
|---|---|---|
| Any | Paste box on their invite page | Bookmark the page |
| Android | PWA Web Share Target: the app appears in the system share sheet | Open the invite link in Chrome → "Install app" |
| iPhone | **"Paste and summarize"** on their page: YouTube → Share → Copy link, then one tap (iOS asks to confirm the paste). Changed 2026-10-16: the owner judged a Shortcut with a pasted token too complex for non-technical friends | Open the invite link in Safari, then Share → Add to Home Screen (on iOS 26 the icon stays signed in) |
| Desktop | Bookmarklet: `open('https://app.<domain>/add#'+encodeURIComponent(location.href))` | Drag link to bookmarks bar |

iOS Safari does not support Web Share Target. The planned Shortcut (Share → Summarize, POSTing
JSON with `Authorization: Bearer`) would have meant pasting a token into it once. The owner chose
the paste button instead. The bearer API stays, and is tested (J6), for anyone who builds a
Shortcut later. The paste button sends clipboard text only when it names a YouTube host. The
bookmarklet uses a `#fragment` so the video URL never reaches the server's request logs.

### 5.3 Mac worker (`worker`, replaces `drain`)

- A LaunchAgent runs it every 60 s; a lock file prevents overlapping runs. It claims jobs until
  the queue is empty or a 30-minute run budget is spent.
- Each job works in `.work/<job_id>/` (gitignored), which is removed by a `trap` on success,
  failure, timeout and SIGTERM. yt-dlp's cache points there (`VSUM_CACHE`), so nothing about
  the video survives the job.
- yt-dlp only ever receives `https://www.youtube.com/watch?v=<id>`, built from a validated
  11-character ID — never user input.
- Duration and caption availability are checked after the metadata fetch and **before**
  `claude` runs. Too-long and no-caption videos cost zero tokens.
- Summarize exactly as `drain` does today (D8):
  `claude -p "$PROMPT" --output-format json --no-session-persistence --model opus --effort high
  --disallowed-tools "<drain's list>"`, run from the repo root with the bundle on stdin and
  capped at 600 s. M5b may replace this with the lean flags or a new engine. `usage` and `total_cost_usd` are read from the
  JSON and sent to the server. `is_error`, empty `result` and invalid front matter are failures.
- A result is kept in `.work/<job_id>/result.json` until the server acknowledges it, so a
  network blip doesn't waste a summary.
- The log records job IDs, error codes and token counts only. It never records URLs, video IDs
  or titles.
- Secrets (`WORKER_TOKEN`, server URL) are kept in `~/.config/smart_yt_consumer/env` with mode
  600, outside the repo.

### 5.4 Intro page

Friends see it the first time they open their invite link (`/welcome`, followed by the setup
steps for their device) and can reach it at `/about` afterwards. Someone without an invite who
lands on the domain sees only "Private, invite-only." There is no name, no explanation and no
login form for them to probe.

Sections, in order. Claude drafts it in M4 from the owner's notes; **the owner rewrites it in
their own voice**, because "trust me" only works in the voice of the person asking.

1. **What this is.** Paste a YouTube link, get back what the video actually says. The length
   follows the number of real claims, so a padded 20-minute video can come back as one line.
   Includes the verdict / watchable / fluff fields and what they mean.
2. **Why I built it.** The owner's story. Seed material: most long-form video is padded for
   retention, the padding is measurable (the fluff table from `README.md`), and the comments
   often catch what the video got wrong.
3. **What I can and can't see.** In plain words: I see that you made a request and how many
   tokens it used. I don't see which video, its title or the summary. Not in my admin page, not
   in any log, not in my email account. Everything about the video is deleted after 30 days.
   Honest caveat: this is how I built it, not a cryptographic guarantee. The data sits on a
   server I control, and I've chosen never to look.
4. **Why there are limits.** It runs on my personal Claude subscription, which I also use for
   my own work. Each summary uses a real share of it. Your limits are 5 a day and 20 a week; ask
   if you need more.
5. **Please don't share your link.** The link *is* your identity: anyone holding it uses your
   quota and gets summaries sent to your email. If you want a friend added, ask me and they'll
   get their own. If a link leaks, I revoke it and send you a new one, no questions asked.
6. **How to reach me.** `hello@ahdimel.com`. Replying to any summary email also lands there.
7. **How to use it.** The setup block for their platform (paste box, Android install, iOS
   paste button, bookmarklet). On `/welcome` this section comes first in the visual order.

### 5.5 Error codes

| Code | Retry? | Counts toward quota? | Friend sees |
|---|---|---|---|
| `invalid_url` | — (rejected at intake) | no | "That doesn't look like a single YouTube video" |
| `unavailable` (private, removed, region) | no | no | "The video isn't publicly available" |
| `members_only` / `age_restricted` | no | no | Plain reason |
| `live_or_upcoming` | no | no | "Try again after the stream ends" |
| `no_captions` | no | no | "No captions, so nothing to summarize" |
| `too_long` | no | no | "Longer than your 3h limit" |
| `fetch_failed` / `rate_limited` | yes, backoff 5/15/45 min, 3 attempts | no | Only on final failure |
| `summarize_failed` / `invalid_output` | yes, 1 retry | no — but tokens are still recorded | Only on final failure |

## 6. Privacy design

What the owner can see, by design:

- **Admin view:** per user, counts (24h / 7d / all), tokens by type, API-equivalent cost, cache
  hits, failures by code, last seen. Per request: user, time, status, error code, tokens, cost.
  **No URL, video ID, title or summary, ever.**

Where content exists, and for how long:

| Place | Content | Lifetime |
|---|---|---|
| Railway SQLite `summaries`, `jobs.video_id` | Yes | Purged after 30 days (D2) |
| Railway request logs | No — content only in POST bodies and fragments | — |
| Railway app logs | No — app never logs bodies, URLs or titles | — |
| Resend dashboard | Video title only (D1) | Resend's retention |
| Friend's inbox | Title + link | Theirs to keep; the link dies after 30 days |
| Mac `.work/<job>/` | Yes, during the job | Deleted at job end |
| Mac `~/.claude/projects/…` | No — `--no-session-persistence` | — |
| Mac drain/worker log | No | — |
| git | No | — |

This is **policy privacy, not cryptographic privacy**. The owner could open the database on
purpose. The guarantee is that nothing surfaces content to the owner in normal operation, and
that it is gone after 30 days. The documentation for friends should say exactly that.

The shared cache leaks nothing between friends. A cache hit looks identical to a fresh
summary, except that it is faster.

## 7. Usage protection

- **Per user:** 5 per rolling 24h, 20 per rolling 7d, max video length 3h. Counted: queued,
  running and done jobs that were not cache hits. Not counted: cache hits, failures.
- **Global:** 40 token-consuming jobs per rolling 24h, enforced at intake. A token ceiling per
  rolling 24h (initial value set after M0 measurements) stops the worker from *claiming*. Jobs
  stay queued rather than being rejected. This is the safety net for abnormally expensive
  videos.
- **Kill switch:** `paused` rejects new submissions and makes `claim` return 204. The admin page
  has a single button for it.
- **Revocation** takes effect on the next request; the cookie stores the token itself, and it
  is checked against `revoked_at` every time.
- **Abuse of failing videos:** tokens spent on failed attempts are recorded against the user,
  even though the failure doesn't count toward their quota. A pattern shows up in the admin view.

Token accounting on a subscription: `usage` is exact, while `total_cost_usd` is an
API-equivalent figure, not a charge. The admin view labels it that way.

## 8. Security

- Invite tokens are 256-bit random, shown once at creation, and stored as SHA-256. Lookup is
  by hash, so there is no timing oracle.
- Cookie: `HttpOnly; Secure; SameSite=Lax; Path=/`, 1 year. No CORS.
  `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex`, and on every page a CSP of
  `default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'`.
- Worker, admin and user credentials are distinct; each route accepts exactly one kind.
- Unknown tokens return 404 (indistinguishable from "no such page"). An IP is rate-limited
  after 10 misses in 10 minutes.
- Body limits: 2 KB on intake, 1 MB on `complete`.
- **Prompt injection:** transcripts and comments are untrusted. With tools disabled, the worst
  an injection can do is shape the summary text, and the renderer fix (§4.3) plus CSP stop
  that text from becoming script.

## 9. Cutover from today's system

- `drain`, `publish`, `lib/index_page.py`, `queue/` and the publish halves of `status` are
  retired. `out/` stays as a read-only archive of the owner's W38–W40 digests.
- The old LaunchAgent is unloaded, and a new one (`com.ahdimel.smartytconsumer.worker`, 60 s)
  is loaded. Its plist goes in the repo this time, as `ops/worker.plist.template`.
- `CLAUDE.md` changes "If the user gives you a YouTube URL". On the Mac, a session posts to the
  API using the owner's token from the env file. A cloud session tells the user to use their
  share sheet, because the git queue no longer exists.
- `./status` becomes: worker LaunchAgent loaded, last successful claim, server `/healthz`,
  queue depth, paused flag, and today's tokens (from an admin-token API call).
- Remove the `$HOME/.nvm/versions/node/v24.15.0` hardcode; resolve `claude` via `bash -lc
  'command -v claude'` at install time.

## 10. Milestones

Each milestone ships with its tests from §11, written alongside the code, and is not done
until they pass.

| # | Milestone | Done when |
|---|---|---|
| **M0** ✅ | **Measure and fix.** `week.py` XSS fix with tests (done). Overhead A/B per §10.1, run 2026-10-15; adoption shelved to M5b (`docs/m0-ab.md`) | Done: XSS tests green; A/B measured; `--no-session-persistence` verified |
| **M1** ✅ | **Server core.** Data model, invites, cookie and bearer auth, URL validation, quotas, cache and coalescing, admin view, pause, worker protocol | Done 2026-10-16: §11 A–E, G green locally (`server/README.md`) |
| **M2** ✅ | **Worker.** Claim/lease loop, per-job dirs, error classification, usage reporting, result retention, LaunchAgent | Done 2026-10-16: §11 F green (`tests/test_worker.py`, `tests/test_worker_server.py`); one real video end-to-end against a local server. The LaunchAgent was installed in M3 and is live against production |
| **M3a** ✅ | **Domain, guided (§10.2).** Pick and buy the domain; connect it to Railway and Resend | Done 2026-10-16: every record answers on 8.8.8.8, 1.1.1.1 and Namecheap's own server; Railway serves HTTPS on `desloppify.ahdimel.com` (CNAME and verify TXT added in M3); Resend green; test mail in the inbox at Gmail and Proton |
| **M3** ✅ | **Delivery.** Summary page with Save-as-PDF, Resend emails, Railway deploy with a volume | Done 2026-10-16: §11 H, I green; email from production passes SPF, DKIM and DMARC at Gmail and Proton; the Mac worker completed one real job end to end against production (`HANDOFF.md`) |
| **M4** ✅ | **Intake modalities and intro page.** PWA manifest and share target, bookmarklet page, a paste button in place of the iOS Shortcut (§5.2), `/welcome` and `/about` (§5.4), with the copy rewritten by the owner | Done 2026-10-17 except two open items: §11 J, M green; verified against production on an iPhone (iOS 26: Safari, Firefox) and a Mac (Firefox). **Open:** Android on a real device (§12), and the owner's rewrite of the draft copy (`HANDOFF.md`) |
| **M5** | **Retention and privacy audit.** Purge job, log audit, admin-response audit | §11 K green; a manual pass over Railway logs shows no content |
| **M5b** | **Summarization revisit — gate before any invite.** Rewrite the summaries so they stand alone for someone who has never seen the video (§10.3). A/B with `tools/ab/` against today's production, including a blind read. Fold in the M0 lean flags if they still hold | §10.3 metrics met; the owner signs off on the summaries of 5 reference videos; tokens per summary recorded and the token ceiling (§7) set from them |
| **M6** | **Cutover.** Retire `drain`, `publish` and the git queue; update README, CLAUDE.md, HANDOFF; invite friends | Old LaunchAgent unloaded; owner and one friend each complete a request in production |

### 10.1 M0 quality A/B: does stripping the overhead change the summaries?

**What is removed:** about 30k tokens of Claude Code's own system prompt. It covers how to act
as a coding agent, tool schemas, git etiquette, and terminal formatting (including "be concise").
None of it concerns summarizing. The summarize prompt is self-contained and stays word for word
the same. With the model pinned (D8), the model is identical in both arms.

**Plausible effects, in both directions:**
- *Better:* nothing pulling toward terminal-style brevity, and nothing distracting about tools
  it can't use anyway.
- *Worse:* drift in output format (front matter, code fences), or a change in register, because
  the model no longer frames itself as Claude Code. Neither has been observed; the A/B is how
  we find out.

**Protocol.**
- **Videos:** the four in `examples/` plus one from `out/2026-W40/`. Their bundles are already
  in `.cache/`, so there is no refetching. The verdicts from the README table serve as known
  answers.
- **Arms:**
  - **A:** today's flags.
  - **B:** stripped flags, prompt passed as the user message.
  - **C:** stripped flags, prompt passed *as* the system prompt.
- **Runs:** each arm twice per video, 30 calls in all. Most of the cost is arm A's overhead.
  Running each arm twice matters: two runs of the *same* arm already differ, and a difference
  between arms only counts if it is larger than that.
- **Measured automatically:**
  - front matter valid;
  - verdict label (skip / skim / watch) agrees with the README;
  - fluff % within ±3 points across arms;
  - number of timestamped claims;
  - word count;
  - "What the comments contest" section present;
  - input/output tokens.
- **Read by the owner:** for 3 videos, the A and B outputs, shown blind in random order. The
  owner picks the better one, or "same".

**Adopt B (or C)** if the automatic checks hold within A's own run-to-run variation and the blind
read doesn't prefer A on balance. Otherwise keep A's flags, still adding
`--no-session-persistence` and `--output-format json`, and accept the overhead. The results go
in `docs/m0-ab.md`.

### 10.2 M3a: domain walkthrough

Mirrors the REI setup (`Documents/vscode/REI/CLAUDE.md`, "DNS & Domain Configuration"),
including the gotchas found there. Claude drives each step and prepares exact values; the owner
clicks. Every step ends with a check Claude runs.

1. ✅ **Choose the name:** `ahdimel.com`, a personal domain usable across projects.
2. ✅ **Buy on Namecheap** (2026-10-15): WHOIS privacy on, auto-renew on, no add-ons.
3. ✅ **Railway custom domain (done 2026-10-16, in M3).** Added with `railway domain
   desloppify.ahdimel.com --service server --port 8080`; Railway verified it and issued the
   certificate within minutes of the records appearing. Needs the M3 Railway service to exist
   first. In the service, under
   Settings → Networking → Custom Domain, enter `desloppify.ahdimel.com`. In Namecheap Advanced
   DNS, add `CNAME desloppify → <id>.up.railway.app.` and the `_railway-verify.desloppify` TXT
   that Railway shows. Because this is a subdomain, it's a standard CNAME, and REI's root-CNAME
   quirk doesn't apply. The root `@` keeps Namecheap's parking page until some project claims
   it. Railway limits: 2 custom domains per service on Hobby, 1 on Trial. This is a new service,
   so REI's domain doesn't count against it. Check: `dig +short CNAME desloppify.ahdimel.com`,
   then `curl -I https://desloppify.ahdimel.com/healthz` once the certificate is issued.
4. ✅ **Email: Resend for apps on `notify.`, Proton Mail for people on the root (done
   2026-10-16).**

   - **People mail:** `hello@ahdimel.com` and `desloppify@ahdimel.com` are real mailboxes on Proton
     Mail Plus ($3.99/mo billed annually; 1 custom domain, 10 addresses). Mail stored there is
     zero-access encrypted, and there's no forwarding hop. Chosen over ImprovMX → Gmail. It's a
     separate inbox from Gmail. No catch-all: it attracts spam, and named addresses suffice.
   - **App mail:** Resend sends from **`notify.ahdimel.com`**, shared by every project, e.g.
     `desloppify@notify.ahdimel.com`.
   - **Why not the root (found 2026-10-16):** Resend mail from `@ahdimel.com` addressed to a
     Proton-hosted `@ahdimel.com` mailbox bounced with `554 5.7.1 rejected by rspamd filter`.
     Proton treats its own hosted domain arriving from outside as spoofing. The same message
     scored 9/10 at mail-tester, with SPF, DKIM and DMARC all passing, so other providers were
     never affected. From the subdomain it was delivered in 5 s. The subdomain also keeps app
     reputation apart from personal mail, as Resend recommends.

   Records in place (Namecheap, `ahdimel.com`):

   | Section | Type | Host | Value | For |
   |---|---|---|---|---|
   | Mail Settings → **Custom MX** | MX | `@` | `mail.protonmail.ch` (10), `mailsec.protonmail.ch` (20) | Proton receiving |
   | Host Records | TXT | `@` | `v=spf1 include:_spf.protonmail.ch ~all`. The only root SPF | Proton sending |
   | Host Records | TXT | `@` | `protonmail-verification=543cbe…`. Keep: Proton re-checks it | Proton ownership |
   | Host Records | CNAME | `protonmail._domainkey`, `protonmail2._domainkey`, `protonmail3._domainkey` | `protonmailN.domainkey.dedfwkl….domains.proton.ch.` | Proton DKIM (2 and 3 are rotation standbys) |
   | Host Records | TXT | `resend._domainkey.notify` | Resend's DKIM key for `notify.` | Resend DKIM |
   | Host Records | CNAME | `send.notify`, `rsend.notify` | `send.forge.rmta.net`, `rsend.forge.rmta.net` | Resend SPF / bounces (no MX needed) |
   | Host Records | TXT | `_dmarc` | `v=DMARC1; p=quarantine;`. Covers `notify.` too | Anti-spoofing for both |

   Verified:
   - Proton → Gmail: SPF, DKIM (`d=ahdimel.com`) and DMARC all PASS; mail-tester 10/10.
   - Resend `notify.` → mail-tester: 9/10. The point lost was the not-yet-live
     `desloppify.ahdimel.com` link.
   - Resend `notify.` → Proton `hello@`: delivered to the inbox, and Reply-To populates `hello@`.

   Gotchas:
   - Namecheap's "Email Forwarding" mode owns the root MX, so use Custom MX.
   - Enter host names short (`send.notify`, not `send.notify.ahdimel.com`).
   - Several TXT records on `@` are fine; several *SPF* records are not.
   - Run `dig` loops under `bash -c`: zsh doesn't word-split `$q`, so `dig +short $q` silently
     looks up the literal name "TXT ahdimel.com".
   - Never ask the owner to `pbpaste` a secret in the same command they copy from chat: the
     command overwrites the clipboard. Use `read -rs` to prompt for it instead.

5. ✅ **API key (done 2026-10-16).** Typed at a hidden `read -rs` prompt and piped into
   `railway variable set RESEND_API_KEY --stdin`; `ops.local.txt` §11. Create a Resend key scoped to "sending access" for `notify.ahdimel.com` only, and set it
   as `RESEND_API_KEY` in Railway, during M3, when the service exists. Use one key per project,
   so revoking one doesn't break the others. It never goes in the repo or on the Mac.
6. ✅ **Deliverability check (done 2026-10-16, from production).** The app's first real email goes to the
   owner's Gmail and one other provider. Open "Show original" and confirm SPF, DKIM and DMARC
   all say PASS. Result: PASS on all three at Gmail and Proton. Proton first rejected the mail
   to `hello@` (`554 5.7.1 rejected by rspamd filter`). Two single-variable sends showed the
   cause: Reply-To equal to To, together with a link to the new hostname. Either alone was
   delivered, so `server/mail.py` drops Reply-To when it equals the recipient. A new domain has no sending reputation, so the first emails may land in spam.
   The welcome email asks friends to add the sender to their contacts.
7. ✅ **Record it.** A "DNS & email" section in this repo's `CLAUDE.md` (2026-10-16).

### 10.3 M5b brief: summaries that stand on their own

**Owner's feedback (2026-10-15):** a summary should read as a summary for someone who has
**never seen the video**. Today's summaries feel anchored in meta-references to the video.

**Measured on production (W38–W40, 41 summaries, body before the comments section):**
- **38–50% of sentences carry a timestamp.** In W40 it is half. The prompt asks for this
  ("use them liberally"), and it's the largest single anchor back to the video's timeline.
- **8–11% of sentences narrate the video as an object:** "the host presses hard", "the
  load-bearing claim arrives at `01:50`", "the title is clickbait", "he concedes".
- **The prompt pulls in this direction structurally.** It asks the body to judge the video ("if
  the video is wrong, say so"), to reorder "if the video buries it", and to cite timestamps
  everywhere. The body ends up as a *review of the video* rather than an *account of the
  subject*.

**Direction to test:**
- **Split the two jobs.** The front matter and verdict block keep everything *about the video*:
  verdict, what is worth watching and where, fluff, the clickbait call. The body becomes a
  standalone explainer of *the subject*, written as an article whose reader will never watch the
  source.
- **Attribute claims to people, not to the video.** "Schmidt's view is that…" or "According to
  Paine…" are fine, the way a news article quotes a source. "The video argues…", "the host…",
  "at 14:30…" and "the episode opens with…" are not.
- **Move timestamps out of the prose.** Options to A/B:
  - none in the body, with "worth watching: `08:00`–`14:30`" in the verdict block only;
  - one chip at the end of each section ("jump to `08:00`");
  - a short "Jump to" list at the end.
- **Fold the evaluation into the content.** Weak evidence becomes "the evidence for this is
  thin: X". "The video gets this wrong" becomes a statement about the claim, not about the
  video.
- **"What the comments contest"** keeps its heading. It is about the video by nature, but it
  should still state the corrections as facts.

**Metrics, scored automatically by `tools/ab/score.py`, extended:**
- sentences with a timestamp, body only: from 38–50% to under 10% (0% if the "none in body"
  variant wins);
- sentences narrating the video: from 8–11% to under 2%;
- a **naive-reader judge:** a separate model call that sees only the summary body and flags
  every sentence that only makes sense to someone who watched the video. Target: zero flags on
  4 of 5 videos;
- the existing checks still hold: valid front matter, verdict stability, and claim coverage. The
  claim count must not fall when timestamps are no longer the way claims are counted, so count
  the claims from pass 1 instead.

**Then the blind read**, the step the owner skipped in M0: 3 videos, production vs. the new
prompt, judged as "would this make sense to me if I'd never heard of the video?"

## 11. Validation tests

`pytest`. Server tests use FastAPI's `TestClient` with a temp SQLite, an injectable clock and a
fake Resend. Worker tests put stub `yt-dlp` and `claude` executables first on `PATH`, emitting
fixtures (including a "canary" title such as `ZZCANARY-7f3a` that privacy tests grep for).

### A. URL validation (`server/urls.py`, pure)

Accept and extract the 11-character ID:

| ID | Input |
|---|---|
| A1 | `https://www.youtube.com/watch?v=dQw4w9WgXcQ` |
| A2 | `http://` scheme; no scheme (`youtube.com/watch?v=…`); `www.` and bare host |
| A3 | `m.youtube.com`, `music.youtube.com`, uppercase host `YOUTUBE.COM` |
| A4 | `youtu.be/ID`, `youtu.be/ID?t=42`, `youtu.be/ID?si=tracking` |
| A5 | `/shorts/ID`, `/live/ID`, `/embed/ID`, `/v/ID`, `youtube-nocookie.com/embed/ID` |
| A6 | `v` not the first param (`?feature=share&v=ID`); `&t=1h2m3s`; `&list=PL…&index=3` (video taken) |
| A7 | IDs containing `-` and `_` |
| A8 | Leading/trailing whitespace and newlines; URL embedded in share text (`"Watch this! https://youtu.be/ID"`) |
| A9 | The same video twice in one input (deduped to one) |

Reject with `invalid_url`:

| ID | Input |
|---|---|
| A10 | Empty, whitespace only, over 2 KB |
| A11 | Non-YouTube (`vimeo.com/…`), lookalikes (`youtube.com.evil.com`, `evilyoutube.com`, `youtube.com@evil.com`, Cyrillic `уoutube.com`) |
| A12 | Playlist-only, channel (`/@handle`, `/channel/UC…`), search, home page |
| A13 | ID of length 10 or 12, or with invalid characters; `v=` empty |
| A14 | Values starting with `-` (yt-dlp option injection); shell metacharacters; `javascript:` and `data:` |
| A15 | Two *different* video IDs in one input (D4) |
| A16 | Canonical URL handed to the worker is always `https://www.youtube.com/watch?v=<id>` |

### B. Authentication and authorization

| ID | Case | Expected |
|---|---|---|
| B1 | `GET /u/{valid}` | 303 to `/`; cookie has `HttpOnly`, `Secure`, `SameSite=Lax`; `Referrer-Policy: no-referrer` |
| B2 | `GET /u/{unknown}` | 404, same body as any missing page |
| B3 | 11 bad tokens from one IP in 10 min | 11th → 429; other IPs unaffected |
| B4 | Revoked user's cookie, and the same token as bearer | 401 on both, on the very next request |
| B5 | `POST /api/requests` with no credentials | 401 |
| B6 | Bearer works on `/api/requests`; cookie works on `/`, `/share`, `/add` |  |
| B7 | Non-admin cookie on `/admin` and `/admin/*` | 404 |
| B8 | User token on `/worker/*`; worker token on user and admin routes | 401 |
| B9 | Token never appears in any response body after creation, or in captured logs |  |
| B10 | Cross-origin POST to `/api/requests` (Origin header from another site, cookie attached by a lax browser) | Rejected by an Origin check; no CORS headers emitted |
| B11 | Invite creation returns the token once; re-reading the user shows only a hash prefix |  |

### C. Quotas, caps, pause

| ID | Case | Expected |
|---|---|---|
| C1 | 5 requests in 24h accepted; 6th | 429 with the time the next slot frees up |
| C2 | Rolling window: 6th request at T₁+24h+1s | Accepted |
| C3 | 20/week spread over 4 days; 21st on day 5 | Rejected (weekly) even though daily is free |
| C4 | Failed jobs don't count | After 5 failures, a 6th request is accepted |
| C5 | Cache hits don't count | 10 cache hits in a day, then a fresh one, are all accepted |
| C6 | Queued and running jobs count |  |
| C7 | Per-user override (`daily_limit = 10`) honoured |  |
| C8 | Global cap: 40 token-consuming jobs across users | 41st rejected for everyone; cache hits still served |
| C9 | Token ceiling reached | Submissions accepted and queued; `claim` returns 204 until the window rolls |
| C10 | Paused | Submissions → 503 with a friendly message; `claim` → 204; resume drains the existing queue |
| C11 | Race: 10 concurrent submissions from a user with 2 slots left | Exactly 2 accepted |
| C12 | Same user, same video, already queued/running | Returns the existing job, creates no new one, uses no quota |
| C13 | `max_minutes` per user reaches the worker in the claim payload |  |

### D. Cache and coalescing

| ID | Case | Expected |
|---|---|---|
| D1 | Video summarized 10 days ago, new request (any user) | Job `done` immediately, `cache_hit`, 0 tokens, email sent |
| D2 | Summary 30 days + 1 s old | Fresh job queued |
| D3 | User B's cache hit on user A's video | Response contains nothing about A; admin row shows `cache_hit` only |
| D4 | Users A and B submit the same uncached video while A's is queued | One summarization; B's job is `coalesced_with` A's; both done with one email each; tokens attributed to A only |
| D5 | The coalesced-to job fails permanently | Both jobs fail with the same code, and both friends are emailed |
| D6 | Failed or invalid summaries are never cached |  |

### E. Worker protocol (server side)

| ID | Case | Expected |
|---|---|---|
| E1 | `claim` with nothing queued | 204; `worker.last_seen` updated |
| E2 | `claim` order | FIFO by `created_at`, skipping jobs whose `not_before` is in the future |
| E3 | Lease expires (Mac slept mid-job) | Next `claim` re-leases it; `attempts` +1 |
| E4 | `complete` twice for one job | Second → 200 no-op; exactly one email |
| E5 | `complete` for a job already failed or re-leased | 409; no state change, no email |
| E6 | `complete` with malformed front matter | 422; job stays leased so the worker can report `invalid_output` |
| E7 | `complete` over 1 MB | 413 |
| E8 | `fail` retryable, attempts 1→3 | Requeued with `not_before` +5, +15 min; 3rd → `failed`, email sent |
| E9 | `fail` permanent (`no_captions`, `too_long`, `unavailable`, `live_or_upcoming`) | `failed` immediately; email states the reason; quota not consumed |
| E10 | Usage from every attempt accumulates on the job |  |
| E11 | Pause while a job is running | Its `complete` is accepted; no further claims |

### F. Worker (Mac side, stubbed tools)

| ID | Case | Expected |
|---|---|---|
| F1 | Successful job | Server receives md + usage parsed from the stub's JSON; `.work/<job>` gone afterwards |
| F2 | Stub `claude` hangs past the cap | Killed, reported as `summarize_failed`; job dir gone |
| F3 | SIGTERM to the worker mid-job | Job dir gone (trap); lease later expires server-side |
| F4 | Duration over `max_minutes` | `too_long`; the `claude` stub is never invoked (asserted via a marker file) |
| F5 | Metadata with no English captions | `no_captions`; `claude` never invoked |
| F6 | yt-dlp stub emits each known error string (private, members-only, upcoming, HTTP 429) | Mapped to the right code and retryable flag |
| F7 | `claude` JSON with `is_error: true`, empty `result`, non-JSON output, exit 0 with empty stdout | `summarize_failed` in every case — never trust the exit code |
| F8 | Model wraps the output in a code fence | Stripped, accepted (existing `clean.py` behaviour) |
| F9 | Second worker started while one runs | Exits immediately on the lock |
| F10 | Server unreachable on `claim` | Exits 0, logs one line, no traceback |
| F11 | Server 5xx on `complete` | Result kept in `.work/<job>/result.json`, retried next run, deleted after the ack |
| F12 | yt-dlp is invoked only with the canonical URL; argv never contains raw user input | Stub records its argv |
| F13 | `claude` argv is D8: the prompt right after `-p`, then `--output-format json --no-session-persistence --model opus --effort high`, and `--disallowed-tools` with `drain`'s list last; no `--tools`; cwd is the repo root | Changed in M2: the `--tools ""` written here first was one of M0's lean flags, shelved to M5b (`docs/m0-ab.md`) |
| F14 | After a job, `git status --porcelain` in the repo is empty |  |
| F15 | After a job, the worker log contains the job ID and does **not** contain the canary title, the video ID or `youtube.com` |  |

### G. Admin view

| ID | Case | Expected |
|---|---|---|
| G1 | Per-user totals for 24h / 7d / all match the seeded jobs |  |
| G2 | Token columns split input / cache-write / cache-read / output; cost labelled "API-equivalent" |  |
| G3 | **Every** admin response (HTML and JSON) over a fixture containing canary titles and video IDs contains neither |  |
| G4 | Create invite → link shown once; revoke → B4 holds; edit limits → C7 holds |  |
| G5 | Pause button toggles C10 behaviour |  |

### H. Email

| ID | Case | Expected |
|---|---|---|
| H1 | Done email: title, link to `/s/<public_id>`, "available until <date>"; HTML + plain-text parts |  |
| H2 | Failed email: title, plain-language reason, "this didn't count against your limit" |  |
| H3 | Title containing `<script>` and `&` | Escaped in HTML; intact in plain text |
| H4 | Resend 5xx | `email_status=pending`, retried by the loop, sent once |
| H5 | Resend 4xx | `email_status=failed`; visible as a count in admin; no retry storm |
| H6 | Coalesced jobs each get exactly one email at their own address |  |
| H7 | Email body contains the title and nothing else from the summary: a fixture's verdict, fluff and body canaries are all absent (D1) |  |

### I. Summary page and renderer

| ID | Case | Expected |
|---|---|---|
| I1 | `/s/<valid>` | 200 with the CSP, `X-Robots-Tag: noindex`, `Referrer-Policy: no-referrer` |
| I2 | `/s/<unknown>` → 404; after retention → 410 |  |
| I3 | `public_id` has ≥128 bits and is not derived from the row ID or time |  |
| I4 | Markdown `[x](javascript:alert(1))` | Rendered as text, not a link |
| I5 | Markdown `[x](" onmouseover="alert(1))` | No attribute injection (the current `week.py` fails this) |
| I6 | Raw `<img src=x onerror=…>` in the body or front matter | Escaped |
| I7 | `https:` links render; timestamps become chips linking to `youtube.com/watch?v=<id>&t=<s>` |  |
| I8 | "What the comments contest" section keeps its styling |  |
| I9 | One-line summary ("This video contains one claim…") renders without empty sections |  |
| I10 | Print stylesheet hides navigation and the Save button; the summary prints in full |  |
| I11 | The 410 page for an expired summary shows no title |  |

### J. Intake modalities

| ID | Case | Expected |
|---|---|---|
| J1 | `POST /share` with the URL in `url` | Accepted |
| J2 | `POST /share` with the URL only in `text` (Android YouTube app does this) | Accepted |
| J3 | `POST /share` with only a title | `invalid_url` page with the paste box pre-shown |
| J4 | `/manifest.webmanifest` declares `share_target` with POST + form-encoded |  |
| J5 | `/add` page script reads `location.hash` and POSTs; the server never sees the URL in a path or query (assert on the request log) |  |
| J6 | Bearer JSON `{url}` and `text/plain` body both accepted | The iOS Shortcut that would have used it was dropped in M4 (§5.2); the API stays |
| J7 | Every route that accepts a video URL rejects GET with query parameters (405) |  |

### K. Retention and privacy

| ID | Case | Expected |
|---|---|---|
| K1 | Purge at day 30 + 1 s | `summaries` row deleted; `jobs.video_id` nulled; usage columns intact; admin totals unchanged |
| K2 | Purge is idempotent and safe to run concurrently with a submit |  |
| K3 | Captured app logs for a full submit → claim → complete → email cycle contain no canary title, video ID or YouTube URL |  |
| K4 | No file under the repo is written by the server or worker outside gitignored paths |  |
| K5 | A real `claude` run with the production flags creates no new file under `~/.claude/projects/` (manual check, M0) |  |

### L. Status and history page

| ID | Case | Expected |
|---|---|---|
| L1 | Shows only the viewer's own jobs; another user's `job_id` cannot be fetched through any status API |  |
| L2 | Shows remaining daily and weekly quota, and when each frees up |  |
| L3 | Worker `last_seen` > 5 min ago with this user's jobs queued | "Waiting for the summarizer to come online" |
| L4 | Queue position is correct across users and excludes `not_before` jobs |  |
| L5 | History is grouped by ISO week, newest first; expired jobs show as "expired" without a title |  |

### M. Intro page and first visit

| ID | Case | Expected |
|---|---|---|
| M1 | First `GET /u/{token}` | 303 → `/welcome`; `welcomed_at` set |
| M2 | Later `GET /u/{token}` (new device) | 303 → `/` |
| M3 | `GET /` with no cookie | 200, the one-line "Private, invite-only." body; no app name, no form, no links |
| M4 | `GET /about` and `/welcome` with no cookie | Same as M3 (not a redirect that reveals the routes exist) |
| M5 | `/welcome` shows the setup block matching the User-Agent (Android / iOS / desktop) first, with the others collapsed |  |
| M6 | The intro page states the friend's own limits from their user row, not hardcoded numbers |  |

## 12. Risks and open questions

- **Terms of service.** This serves other people from a personal Claude subscription. The owner
  chose this knowingly. Read Anthropic's current consumer terms before inviting friends, and
  keep the API-key path in mind. The worker would only need `ANTHROPIC_API_KEY` and a
  `--max-budget-usd` flag.
- **Android share target and `SameSite=Lax`.** Whether Chrome attaches a Lax cookie to an
  OS-initiated share-target POST must be verified on a device in M4. Fallback: a service worker
  catches the share POST and re-issues it same-origin. **Still open after M4** (no Android phone
  to hand). Each `/share` logs `share site=… origin=… cookie=…`, which answers it on first use.
- **Laptop availability.** Jobs wait while the MacBook sleeps (D6). The status page sets that
  expectation. If friends find it frustrating, revisit D6.
- **Subscription limits are invisible.** The CLI reports tokens, not how close the account is
  to its 5-hour or weekly limits. The token ceiling (§7) is a proxy, tuned from M0 measurements.
- **YouTube changes** break yt-dlp periodically. Keep `brew upgrade yt-dlp` in the worker's
  weekly maintenance, and alert via the admin page's failure-by-code counts.
- **SQLite on a Railway volume** is a single instance, with no replicas. That's acceptable at ≤10
  users; back up `users` nightly (content is disposable by design).

## 13. Out of scope

Accounts that friends manage themselves, payments, non-YouTube sources, follow-up questions
about a summary, alerting the owner by email (the admin page shows failures), multiple workers.
