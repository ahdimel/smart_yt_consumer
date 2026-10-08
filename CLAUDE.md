# smart_yt_consumer

URL in → summary out. Strips YouTube video essays and podcasts to what they actually say.
Read `README.md` for the method, the pipeline and setup. Read `HANDOFF.md` for current state,
known gaps and what is specific to the owner's machine.

## If the user gives you a YouTube URL

**Queue it. Do not try to process it yourself** unless you are running on the user's Mac
and `yt-dlp` is available. The fetch needs a residential IP — YouTube bot-checks datacenter
addresses, so a cloud session running `yt-dlp` will fail intermittently and confusingly.

To queue, write the URL to a new file and push:

```sh
echo "<url>" > "queue/$(date +%s)-queued.txt"
git add queue && git commit -m "queue: <video title or url>" && git push
```

Then tell the user it is queued and will appear in this week's digest once published. That's the
whole job.

Pushing to your own branch instead of `main` is fine — `drain` adopts any `claude/*` branch whose
diff touches only `queue/`, merges it, and deletes the branch. Don't open a PR for a queued URL;
it just creates cleanup. Branches that change anything outside `queue/` are left alone for
normal review.

## Where this lives, and why it is not in Documents/vscode

`~/code/smart_yt_consumer` — deliberately outside `~/Documents`, unlike the owner's other
projects. macOS TCC blocks LaunchAgents from reading `~/Documents`, `~/Desktop` and
`~/Downloads`: the scheduled drain failed with "Operation not permitted" on every run while the
repo lived there, and the agent's own log was the only place that said so. Do not move it back.

## If you are on the user's Mac

`./drain` — processes everything in `queue/`, writes summaries to `out/<ISO-week>/`, regenerates
that week's page and the index page, commits and pushes. It republishes the artifacts only when
run from a Claude Code session (see "Publishing is manual"). A LaunchAgent
(`~/Library/LaunchAgents/com.ahdimel.smartytconsumer.plist`, not in the repo; its contents are
in `README.md`) runs it every 15 minutes while the Mac is awake; it logs to
`~/Library/Logs/smart_yt_consumer/drain.log`. **Check that log before believing the timer
works** — `launchctl list` showing the job is not evidence it ran.

`./publish` — republishes every stale week artifact and the index, records `published_sha`,
commits and pushes. Only works from inside a Claude Code session.

`./vsum <url>` — one-off, bypasses the queue. Set `VSUM_FETCH_ONLY=1` for the bundle only.

## Checking health

`./status` — timer loaded, when it last ran, queue depth, whether each week's artifact matches
its page, and any failures in the last two days. Run this before believing anything works.

## Publishing is manual

The scheduled drain fetches, summarizes, rebuilds the pages and pushes, but does **not** publish.
`claude -p` only has the Artifact tool when launched from inside a Claude Code session; under
launchd it never does. So after new summaries land, the week's artifact is stale until someone
publishes from a session. `./status` shows "NOT PUBLISHED: <week>" while it is stale.

**If the user asks why new videos are missing from the digest, check this first.** The usual
answer is that the summaries exist in `out/<week>/` and the artifact has not been republished.

To publish from a session, either run `./publish`, or do it directly with the Artifact tool:

1. Publish `out/<week>/index.html`. If `out/<week>/meta.json` has an `artifact_url`, `read` that
   artifact first and pass the URL as `url`. If there is no `meta.json`, it is a new week:
   publish fresh with icon `calendar` and write `week`, `artifact_url` and `published` into a
   new `meta.json`.
2. Set `published_sha` in `meta.json` to the first 16 hex characters of the page's SHA-256.
   `./status` compares against this.
3. Run `python3 lib/index_page.py`, `read` the index artifact at the URL in
   `out/index.meta.json`, and republish `out/index.html` to that URL.
4. Run `./status` and confirm "all weeks published and current", then commit `out/`.

Publishing without `url` creates a *duplicate* artifact instead of updating the week. Always
check `meta.json` before publishing.

**Never report a publish as successful without checking.** `claude -p` exits 0 whenever the
session ends, published or not. On the W39 rollover it published nothing twice while the log
said "artifact published" both times, because drain trusted the exit code and sent all output to
/dev/null. `drain` and `publish` now require the model to echo the URL back, and a headless
session without the Artifact tool is expected to refuse rather than echo one.

## Layout

```
vsum                fetch one URL -> bundle (-> summary if the claude CLI is present)
drain               process the queue, rebuild the week and index pages, commit, push
publish             republish stale week artifacts and the index (Claude Code session only)
status              health check
lib/flatten.py      VTT -> timestamped prose; prefers manual captions, dedupes auto-captions
lib/bundle.py       metadata + transcript + top comments, creator/low-signal filtered
lib/clean.py        validate a raw summary's front matter, strip code fences, stamp `added`
lib/week.py         out/<week>/*.md -> one navigable page
lib/index_page.py   out/*/meta.json -> the standing index page
lib/page.html       the week page template
lib/repair.py       rewrite one summary's front matter into canonical form
lib/repair_all.py   find and repair every malformed summary in a week directory
prompts/            the two-pass summarization prompt
queue/              one file per queued URL; drain deletes each after summarizing it
out/<week>/         per-video summaries (.md), meta.json, index.html, .publish.log
out/index.html      the standing index page; its artifact URL is in out/index.meta.json
examples/           early reference outputs, in the older format without front matter
.cache/             yt-dlp downloads and bundles, gitignored
```

## Conventions

- Summaries carry front matter: `nav, title, channel, duration, views, verdict, watchable,
  fluff, compression, added`. Each field is a single line. `lib/week.py` reads these; the body
  is the prose.
- Never edit `out/<week>/index.html` or `out/index.html` by hand; they are regenerated.
- Wrap markdown at ~98 columns.
- Timestamps in body text go in backticks — `lib/week.py` renders them as jump chips.
- The closing section must be titled "What the comments contest" — that heading triggers
  its own styling.
- **Do not report word-compression ratio as a fluff signal.** It doesn't work; see README.
