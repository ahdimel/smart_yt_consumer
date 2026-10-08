# smart_yt_consumer

URL in → summary out. Strips YouTube video essays and podcasts down to what they actually say,
and collects each week's summaries into one page.

Built around one observation: most long-form video is padded for retention, and the padding is
*measurable*. A summary's length should track the surviving claim count, not a word target — so a
22-minute video with one real idea gets one line, and a 109-minute lecture with sixty gets pages.

This is currently a single-user setup running on one Mac. `HANDOFF.md` lists what is specific to
that machine and what is not yet solved.

## What it does

```
queue/<ts>-queued.txt      a file containing one YouTube URL, pushed to this repo
        │
        ▼   ./drain  (every 15 min, from a macOS LaunchAgent)
fetch → flatten → bundle → summarize
        │
        ▼
out/<ISO-week>/<video-id>.md     one summary per video, committed and pushed
out/<ISO-week>/index.html        the week's page, rebuilt from the summaries
out/index.html                   a standing index of every week
        │
        ▼   ./publish  (manual, from inside a Claude Code session)
one Claude artifact per week + one index artifact
```

Everything up to and including the pushed HTML is automatic. Publishing the artifacts is a manual
step; see [Publishing](#publishing).

## Use

Queue a video (from anywhere that can push to the repo):

```sh
echo "https://www.youtube.com/watch?v=..." > "queue/$(date +%s)-queued.txt"
git add queue && git commit -m "queue: <title or url>" && git push
```

Pushing to a `claude/*` branch instead of `main` also works: `drain` merges any such branch whose
diff touches only `queue/`, then deletes it. That is how Claude Code on the web queues from a
phone.

On the Mac that runs the pipeline:

| Command | What it does |
|---|---|
| `./drain` | Process everything in `queue/`, rebuild the week's page, commit, push. |
| `./publish` | Republish every stale week artifact and the index. Run inside a Claude Code session. |
| `./status` | Timer loaded, last run, queue depth, which weeks are unpublished, recent failures. |
| `./vsum <url>` | One-off fetch and summary, bypassing the queue. `VSUM_FETCH_ONLY=1` stops at the bundle. |

## How it works

1. **Fetch** (`vsum`) — `yt-dlp` pulls captions, metadata and top comments. No video download.
   ~10 seconds, ~12k tokens for a 44-minute video. Cached under `.cache/`, so re-runs are free.
2. **Flatten** (`lib/flatten.py`) — VTT → timestamped prose blocks. Prefers manual captions over
   auto-generated ones; auto-captions carry rolling-window duplication and inline word timings
   that cost 5x the bytes for identical text. Unescapes HTML entities, drops `[music]`, marks
   speaker turns.
3. **Bundle** (`lib/bundle.py`) — metadata + transcript + top comments, with creator comments,
   sub-25-character comments and engagement noise filtered out.
4. **Summarize** (`prompts/summarize.md`) — one `claude -p` call per video with tools disabled.
   The prompt works in two passes: pass 1 extracts a deduplicated claim list with timestamps and
   names what was cut as fluff; pass 2 writes it up, at whatever length the surviving claims
   require. Only the finished summary, with front matter, is emitted.
5. **Clean** (`lib/clean.py`) — strips a stray code fence, checks the front matter, stamps the
   ingest time. A summary that fails the check is discarded and the URL stays queued.
6. **Week page** (`lib/week.py`, `lib/page.html`) — renders `out/<week>/*.md` into one navigable
   page, newest first, with timestamps as chips and the comments section styled separately.
7. **Index** (`lib/index_page.py`) — one page listing every week with its artifact link.

`lib/repair.py` and `lib/repair_all.py` are maintenance tools: they rewrite the front matter of
summaries whose metric fields are not in the canonical format (`python3 lib/repair_all.py
out/<week>`).

## Publishing

Each ISO week gets its own Claude artifact, republished in place as videos are added; a standing
index artifact links to all of them. The URLs are stored in `out/<week>/meta.json` and
`out/index.meta.json`.

The scheduled `drain` cannot publish. `claude -p` only has the Artifact tool when it is started
from inside a Claude Code session, and a LaunchAgent is not one. So `drain` stops after pushing
the page, and the artifact is stale until someone publishes from a session — either by running
`./publish` there or by asking Claude to publish. `./status` shows `NOT PUBLISHED: <week>` until
then; it compares a hash of the page against the `published_sha` recorded in `meta.json`.

## Why comments

Not for sentiment. They're a correction layer: domain experts catching errors, disputes the video
never addresses, and crowd-sourced "the real point starts at 14:30". In testing this reliably
surfaced things the videos got wrong. On low-quality finance content it surfaces something else —
astroturfed book plugs and advisor scams. Both are useful to know.

## What testing changed

**Word-compression ratio is a bad fluff detector.** Across five videos spanning a 19-minute
listicle to a 109-minute lecture, the ratio stayed in a narrow 5.7:1–10.9:1 band *and inverted* —
the thinnest video compressed least, the densest compressed most. Thin content still needs prose
to frame its few claims; dense content states a lot per word.

What does discriminate, by ~60x, is the fluff fraction: the summed duration of ad reads, teasers,
restatement and B-roll narration, divided by runtime.

| Video | Runtime | Fluff | Compression | Verdict |
|---|---|---|---|---|
| Sandeep Swadia — money upgrades | 19m | **34%** | 6.9:1 | skip entirely |
| Prof G — $40T debt | 22m | **13%** (3 ad reads) | 5.7:1 | skim |
| Maxinomics — rare earths | 27m | **6%** | 7.3:1 | watch |
| Veritasium — Bell's theorem | 44m | **4%** | 10.9:1 | watch |
| Sarah Paine — Mao | 109m | **<1%** | 10.0:1 | watch all |

`examples/` holds four of these outputs. They predate the front-matter format the pipeline now
emits; for the current format, look at any file in `out/<week>/`.

## Setup

Requirements: macOS, `yt-dlp`, Python 3 (standard library only), `git` with push access to the
repo, and the `claude` CLI, logged in.

The fetch must run from a residential IP. YouTube bot-checks datacenter addresses, so `yt-dlp`
fails intermittently from cloud machines.

Clone to `~/code/smart_yt_consumer`, not under `~/Documents`, `~/Desktop` or `~/Downloads`. macOS
TCC blocks LaunchAgents from reading those folders, and the scheduled drain fails there with
"Operation not permitted".

The timer is a LaunchAgent that is not checked into the repo. Save this as
`~/Library/LaunchAgents/com.ahdimel.smartytconsumer.plist`, adjusting the paths:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.ahdimel.smartytconsumer</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>/Users/ahdimel/code/smart_yt_consumer/drain</string>
  </array>
  <key>StartInterval</key>
  <integer>900</integer>
  <key>RunAtLoad</key>
  <false/>
  <key>StandardOutPath</key>
  <string>/Users/ahdimel/Library/Logs/smart_yt_consumer/drain.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/ahdimel/Library/Logs/smart_yt_consumer/drain.log</string>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
```

Then `mkdir -p ~/Library/Logs/smart_yt_consumer` and
`launchctl load ~/Library/LaunchAgents/com.ahdimel.smartytconsumer.plist`. It runs every 15
minutes while the Mac is awake and the user is logged in, and comes back by itself after a
reboot. Run `./status` to confirm it is actually firing; `launchctl list` showing the job is not
evidence that it ran.
