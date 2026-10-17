# server/

The Railway app from `docs/PROPOSAL.md` §5.1: intake, quotas, the shared cache, the worker
protocol, the admin view (M1), delivery: the summary page and Resend email (M3), and the intake
modalities and intro page (M4). Tested against §11 A–E and G–J, plus M. It has no retention
purge yet (M5).

## Run and test

```sh
/Users/ahdimel/.pyenv/versions/3.13.2/bin/python3 -m venv server/.venv   # 3.13, as .python-version
server/.venv/bin/pip install -r server/requirements-dev.txt
server/.venv/bin/pytest -c server/pytest.ini server/tests    # the static/*.js tests need node

# local server: the DB defaults to ~/.local/share/smart_yt_consumer/server.db, outside the repo
export WORKER_TOKEN=dev-worker COOKIE_SECURE=0 PUBLIC_ORIGIN=http://127.0.0.1:8000
server/.venv/bin/python -m server.cli invite --name Owner --email hello@ahdimel.com --admin
server/.venv/bin/uvicorn server.app:create_app --factory --no-access-log
```

Keep `--no-access-log`. Access lines record paths, and `/u/<token>` and `/s/<public_id>` are
credentials in a path.

`server/smoke.sh` runs one request end to end under real uvicorn, with curl standing in for the
worker. It uses a throwaway database. M2 can copy the request and response shapes from it.

| Env | Meaning |
|---|---|
| `DB_PATH` | SQLite file. On Railway this is the volume, e.g. `/data/server.db` |
| `WORKER_TOKEN` | The Mac worker's bearer. Unset means every `/worker/*` call is refused |
| `PUBLIC_ORIGIN` | `https://desloppify.ahdimel.com`. Used for invite links and the Origin check |
| `COOKIE_SECURE` | `0` only for plain-HTTP local runs |
| `CLIENT_IP_HEADER` | The header Railway's edge sets with the client IP, for the token-miss limiter. Set it only behind that edge: clients can forge it |
| `LEASE_SECONDS` | How long a claimed job stays leased (default 1800) |
| `RESEND_API_KEY` | Send-only Resend key for `notify.ahdimel.com`. Unset means no mailer: email waits at `pending` |
| `MAIL_FROM`, `MAIL_REPLY_TO` | Default `desloppify <desloppify@notify.ahdimel.com>` and `hello@ahdimel.com` |
| `RESEND_API_URL` | Tests only: points the mailer at a fake Resend |

## Production (Railway)

`Dockerfile` at the repo root; Railway builds it because it is there. The image holds `server/`
and `lib/week.py`, nothing else. One replica, with a volume mounted at `/data` and
`DB_PATH=/data/server.db`. The healthcheck path, `/healthz`, is set in the service's settings:
Railway no longer lets new services use `railway.json`, and its replacement
(`.railway/railway.ts`) wasn't worth adopting for one setting.
Deploys are `railway up` from a clean `main`, never on push: drain pushes to `main` every 15
minutes. The exact commands, including running `server.cli` inside the service with `railway
ssh`, are in `ops.local.txt` on the owner's Mac.

`CLIENT_IP_HEADER`: Railway's docs name `X-Real-IP` as the client IP, but don't say whether a
client's own copy is replaced. The check: send ten bad tokens with one forged `X-Real-IP`, then
one with a different forged value. If that one gets 429, the edge overwrote the header.
**Checked against production on 2026-10-16:** ten 404s, then 429 for the different forged value
and 429 with no header at all. Every request was keyed on the real client IP, so
`CLIENT_IP_HEADER=X-Real-IP` is safe.

## Layout

| File | Role |
|---|---|
| `urls.py` | Input text → one 11-character video ID, or `InvalidURL`. Pure |
| `intake.py` | Submit: in-flight dedupe, cache hit, coalescing, quotas. One `BEGIN IMMEDIATE` transaction |
| `protocol.py` | Worker `claim` / `complete` / `fail`, leases, retry policy |
| `codes.py` | Error codes: attempts, backoff, the friend-facing sentence |
| `admin.py` | Usage aggregation and the admin page. Never selects content columns |
| `auth.py` | Token hashing, the per-IP miss limiter, the Origin check |
| `mail.py` | Outbox, Resend transport and the copy: exactly one email per finished job |
| `render.py`, `summary.html` | The summary page, rendered from stored markdown by `lib/week.py` |
| `pages.py` | The friend-facing pages: home, `/add`, the intro page's layout, refusal pages |
| `intro.py` | **The words** of `/welcome` and `/about`, as HTML fragments. The owner's to rewrite |
| `static/` | `app.css`; `summary.css` and `summary.js` (Save as PDF); `paste.js` (Paste and summarize); `add.js` (the bookmarklet page); the icons, drawn by `ops/make-icons` |
| `app.py` | Routes and the credential each one accepts |
| `cli.py` | `invite` (the first admin), `reissue` (a lost admin link), `test-email` |

## Choices the proposal left open

Made while building M1. Revisit any of them by changing the code and its test.

- **Coalesced jobs don't count toward the rider's quota**, the same as cache hits: they spend
  no tokens. The tokens stay on the primary job (D4).
- **A coalesced group uses the primary requester's `max_minutes`.** If a rider's limit is
  higher, a `too_long` failure still fails them too. With everyone on 180 this doesn't happen.
- **Pause rejects cache hits too.** "Rejects new submissions" was taken literally.
- **Retries:** `fetch_failed` and `rate_limited` get 3 attempts with backoffs of 5 and 15
  minutes. The 45-minute step in §5.5 would come after the third, final attempt, so it is never
  used. `summarize_failed` and `invalid_output` get 2 attempts, 5 minutes apart. Lease expiries
  count as attempts.
- **Leases carry a random `lease_id`.** `complete` and `fail` must quote it, which is how a
  worker whose lease expired is told 409 (E3, E5). This adds a column not in §5.1.
- **The token ceiling sums all four token types over a rolling 24h.** The window is keyed on
  `jobs.usage_at`, the time usage was last reported, so a backlog drained after the Mac wakes
  counts when it runs. This adds another column not in §5.1. The ceiling is unset until M5b
  measures a summary.
- **Admin is cookie-only.** A request to `/admin*` that carries an `Authorization` header gets
  401 (B8). Anything else without an admin cookie gets the plain 404 (B7). `/admin/usage.json`
  gives the same data as the page, for the future `./status`.
- **Re-key a user** (`POST /admin/users/{id}/reissue`) replaces a leaked link and keeps the
  user's history (§5.4 ¶5).
- **IDs starting with `-` are accepted** (A14). Real IDs can start with a dash. The
  option-injection risk is closed because yt-dlp only ever receives `canonical(id)`, which
  starts with `https://`. A bare ID with no URL is rejected.
- **Intake's 2 KB limit applies to the HTTP body** (413) and to the text (`invalid_url`).
- **Email status gains `sending`.** It is a claim taken before calling the mailer, so
  concurrent deliveries can't both send. With no mailer configured, finished jobs stay
  `pending`.
- **Email delivery (M3).** The first attempt runs right after the response that finished the
  job. After that, a loop in the app retries every 30 s, honouring each job's backoff: 1, 5, 15
  and 60 minutes, then 3 hours. After 6 attempts, about 4.5 hours, the email is `failed`. 5xx,
  408, 409, 429 and network errors are transient. Any other 4xx fails at once, with no retry
  (H5). A `sending` row older than 10 minutes is reset to `pending`. Each job's attempts share
  one Resend `Idempotency-Key`, so a reset can't double-send within Resend's 24 h window.
  Columns `email_attempts`, `email_not_before` and `email_claimed_at` are added, by `ALTER
  TABLE` on start when missing.
- **Failure emails carry no title** (H2 asks for one). A failed job has none: the worker
  doesn't report one and the server never fetches one. The email names the time of the request
  instead. Having the worker send the yt-dlp title with `fail` would fix it; that touches the
  worker, so it waits for M5b.
- **The summary page link ends with the shorter of two lifetimes:** the summary's `expires_at`
  and the job's own `finished_at` + 30 days. So a cache hit near the end of the window ends with
  the summary, and a summary refreshed by someone else's later request doesn't revive an old
  link. Jobs that aren't `done` are 404, like unknown IDs.
- **Timestamp chips link into the video** (`watch?v=<id>&t=<s>s`). The server adds the links
  after `lib/week.py` renders, so the week pages drain publishes are unchanged.
- **The summary page uses system fonts.** The week page loads Google Fonts, which the CSP
  forbids, and which would tell Google who reads what.
- **For M5's log audit:** Railway's edge logs request paths, so invite tokens (`/u/<token>`)
  and summary capability IDs (`/s/<public_id>`) appear in Railway's HTTP logs, which the owner
  can read. The app's own logs contain neither, and no addresses or titles.

## Intake and the intro page (M4)

Choices made while building M4, and what production showed:

- **iPhone has no Shortcut.** The owner chose a "Paste and summarize" button on the home page
  instead (2026-10-16): a Shortcut meant pasting a token into it, too fiddly for the friends in
  mind. `paste.js` reads the clipboard only on a tap, and sends it only when it names a YouTube
  host. Anything else (a password, an address) never leaves the device. The bearer API is
  unchanged.
- **`/share` and the paste box answer with pages.** Success and the known refusals (invalid,
  quota, busy, paused) redirect to `/?m=<code>`. 401 shows the private page, and 400, 403,
  413, 415 and 429 show a sentence with a link home. JSON clients keep JSON.
- **`/share` logs where it came from:** `share site=<Sec-Fetch-Site> origin=<absent|null|self|
  other> cookie=<yes|no>`. Every cross-origin refusal logs the same categories. Values outside
  the known set become `other`, so a header can't smuggle anything into the log. This is how
  §12 (Chrome's Lax cookie on an OS share) gets answered on the first real share.
- **No service worker.** Chrome on Android installs from the menu without one since 108 (WebAPK:
  109). It stays in reserve as §12's fallback.
- **The manifest and icons are public.** A linked manifest is fetched without cookies, and the
  hostname already names the app. Strangers' pages don't link it (M3).
- **`/add` refuses any query string** (405), so nobody builds a bookmarklet that logs the URL.
  `add.js` wipes the fragment from the address bar before posting.
- **`/about` ends with the setup blocks.** §5.4 calls `/about` "the intro page alone", but a
  friend setting up a second device needs them somewhere. `/welcome` puts them first (§5.4 ¶7).
- **Platform detection** is a substring match on `Android` and `iPhone|iPad|iPod`. iPads that
  ask for the desktop site get the desktop block first. Safari on iOS 26 reports `iPhone OS
  18_7`, so never match a version.
- **Seen on real devices (2026-10-16/17):** Firefox (macOS, iOS) and Safari (iOS 26) send
  `Origin: null` with `Sec-Fetch-Site: same-origin` on the paste box and on `add.js`'s `fetch`,
  and both pass. On iOS every browser app has its own cookies. Safari's Add to Home Screen carries
  the login into the icon.

## Not yet built

M4 leftovers: Android verified on a real device (`HANDOFF.md`, "Open from M4"). The status and
history page (§11 L) is still a minimal list on `/`.
M5: the retention purge (§11 K).
