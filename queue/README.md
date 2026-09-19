# Queue

One file per URL. Anything that can write a file here can feed the pipeline:
Claude Code on the web from a phone, a share-sheet Shortcut, this repo's own scripts.

Filename: `<unix-timestamp>-<anything>.txt`  ·  Contents: a single YouTube URL.

`./drain` processes every file here, then deletes it. Never edit `out/` by hand —
it is regenerated from the summaries.
