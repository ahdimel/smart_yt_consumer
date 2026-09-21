# smart_yt_consumer

URL in → summary out. Strips YouTube video essays and podcasts down to what they actually say.

Built around one observation: most long-form video is padded for retention, and the padding is
*measurable*. A summary's length should track the surviving claim count, not a word target — so a
22-minute video with one real idea gets one line, and a 109-minute lecture with sixty gets pages.

## Use

```sh
./vsum "https://www.youtube.com/watch?v=..."
```

Fetches transcript + top comments, builds a model-input bundle, and (when the `claude` CLI is
installed) writes a summary to `out/`. Cached under `.cache/` so re-runs are free.

## How it works

1. **Fetch** (`vsum`) — `yt-dlp` pulls captions, metadata and top comments. No video download.
   ~10 seconds, ~12k tokens for a 44-minute video.
2. **Flatten** (`lib/flatten.py`) — VTT → timestamped prose blocks. Prefers manual captions over
   auto-generated ones; auto-captions carry rolling-window duplication and inline word timings
   that cost 5x the bytes for identical text. Unescapes HTML entities, drops `[music]`, marks
   speaker turns.
3. **Bundle** (`lib/bundle.py`) — metadata + transcript + top comments, with creator comments,
   sub-25-character comments and engagement noise filtered out.
4. **Summarize** (`prompts/summarize.md`) — two passes. Pass 1 extracts a deduplicated claim list
   with timestamps and names what was cut as fluff. Pass 2 writes it up, at whatever length the
   surviving claims require.

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

What does discriminate, by ~60x:

| Video | Runtime | Fluff | Compression | Verdict |
|---|---|---|---|---|
| Sandeep Swadia — money upgrades | 19m | **34%** | 6.9:1 | skip entirely |
| Prof G — $40T debt | 22m | **13%** (3 ad reads) | 5.7:1 | skim |
| Maxinomics — rare earths | 27m | **6%** | 7.3:1 | watch |
| Veritasium — Bell's theorem | 44m | **4%** | 10.9:1 | watch |
| Sarah Paine — Mao | 109m | **<1%** | 10.0:1 | watch all |

See `examples/` for the full outputs.

## Location

`~/code/smart_yt_consumer`, not `~/Documents`. macOS TCC blocks background LaunchAgents from
reading `~/Documents`, so the scheduled drain cannot run from there.

## Requirements

`yt-dlp`, Python 3, and the `claude` CLI for the summarize step.
