# Queue

One file per URL. Anything that can write a file here can feed the pipeline:
Claude Code on the web from a phone, a share-sheet Shortcut, this repo's own scripts.

Filename: `<unix-timestamp>-<anything>.txt`  ·  Contents: a single YouTube URL.

`./drain` processes every file here and deletes each one once its summary is written; a URL
that fails to fetch or summarize stays here and is retried on the next run. The week's artifact
is republished separately with `./publish`. Never edit `out/` by hand —
it is regenerated from the summaries.
