# smart_yt_consumer

URL in → summary out. Strips YouTube video essays and podcasts to what they actually say.
Read `README.md` for the method and what testing changed.

## If the user gives you a YouTube URL

**Queue it. Do not try to process it yourself** unless you are running on the user's Mac
and `yt-dlp` is available. The fetch needs a residential IP — YouTube bot-checks datacenter
addresses, so a cloud session running `yt-dlp` will fail intermittently and confusingly.

To queue, write the URL to a new file and push:

```sh
echo "<url>" > "queue/$(date +%s)-queued.txt"
git add queue && git commit -m "queue: <video title or url>" && git push
```

Then tell the user it is queued and will appear in this week's digest. That's the whole job.

Pushing to your own branch instead of `main` is fine — `drain` adopts any branch whose diff
touches only `queue/`, merges it, and deletes the branch. Don't open a PR for a queued URL;
it just creates cleanup. Branches that change anything outside `queue/` are left alone for
normal review.

## Where this lives, and why it is not in Documents/vscode

`~/code/smart_yt_consumer` — deliberately outside `~/Documents`, unlike the owner's other
projects. macOS TCC blocks LaunchAgents from reading `~/Documents`, `~/Desktop` and
`~/Downloads`: the scheduled drain failed with "Operation not permitted" on every run while the
repo lived there, and the agent's own log was the only place that said so. Do not move it back.

## If you are on the user's Mac

`./drain` — processes everything in `queue/`, writes summaries to `out/<ISO-week>/`,
regenerates that week's page, commits, and republishes the weekly artifact. A LaunchAgent
(`~/Library/LaunchAgents/com.ahdimel.smartytconsumer.plist`) runs it every 15 minutes while the
Mac is awake; it logs to `~/Library/Logs/smart_yt_consumer/drain.log`. **Check that log before
believing the timer works** — `launchctl list` showing the job is not evidence it ran.
`./vsum <url>` — one-off, bypasses the queue. Set `VSUM_FETCH_ONLY=1` for the bundle only.

## Checking health

`./status` — timer loaded, when it last ran, queue depth, whether this week actually published,
and any failures in the last two days. Run this before believing anything works.

## Weekly artifact

One artifact per ISO week, republished in place as videos are added. The URL lives in
`out/<week>/meta.json` under `artifact_url`.

There is also a **standing index** artifact listing every week, so a new week's URL is
discoverable — its URL is in `out/index.meta.json` and `drain` refreshes it after each run.
Each week still gets its own artifact.

**Never report a publish as successful without checking `meta.json`.** `claude -p` exits 0
whenever the session ends, published or not. On the W39 rollover it published nothing twice
while the log said "artifact published" both times, because drain trusted the exit code and
sent all output to /dev/null.

**Publishing rule that matters:** to update an existing week's artifact from a conversation
that did not create it, you must pass that stored `artifact_url` as the `url` parameter, and
you must `read` it first. Publishing without `url` creates a *duplicate* artifact instead of
updating the week. Always check `meta.json` before publishing. If no `meta.json` exists for
the current week, it's a new week — publish fresh and write the returned URL into it.

## Layout

```
vsum            fetch one URL -> bundle (-> summary if the claude CLI is present)
drain           process the queue, rebuild the week, publish
lib/flatten.py  VTT -> timestamped prose; prefers manual captions, dedupes auto-caption rolling window
lib/bundle.py   metadata + transcript + top comments, creator/low-signal filtered
lib/week.py     out/<week>/*.md -> one navigable page
lib/page.html   the page template
prompts/        the two-pass summarization prompt
out/<week>/     per-video summaries (.md), meta.json, index.html
examples/       reference outputs — what good looks like
```

## Conventions

- Summaries carry front matter: `nav, title, channel, duration, views, verdict, watchable,
  fluff, compression, added`. `lib/week.py` reads these; the body is the prose.
- Wrap markdown at ~98 columns.
- Timestamps in body text go in backticks — `lib/week.py` renders them as jump chips.
- The closing section must be titled "What the comments contest" — that heading triggers
  its own styling.
- **Do not report word-compression ratio as a fluff signal.** It doesn't work; see README.
