#!/usr/bin/env python3
"""Rewrite one summary's front matter into the canonical format.

Cheap: sends only the existing summary, not the source bundle.
"""
import sys, os, re, subprocess, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import week as W

SPEC = """Below is a video summary whose front matter uses inconsistent formats.
Rewrite ONLY the front-matter block. Keep the body byte-for-byte identical.

Required formats, each on a single line, unquoted, no YAML block scalars:
  verdict:     starts with **Watch it.** / **Skim.** / **Skip the video.** /
               **Watch the whole thing.** in bold, then one or two sentences.
  watchable:   "N of M min" with bare numbers, e.g. "~25 of 27 min" or "0 of 19 min".
               Never a timestamp range, never prose.
  fluff:       a bare percentage like 13%. Never "high"/"low". Infer it from the body's
               description of ads, teasers, restatement and B-roll if not already numeric.
  compression: "<transcript words> -> <summary words> words (X.Y:1)", all three parts.
Keep nav, title, channel, duration, views, added exactly as they are.

Output the complete corrected file, starting with --- and nothing before it.
No code fence."""

def main(path):
    src = open(path, encoding='utf-8').read()
    out = subprocess.run(
        ['claude', '-p', SPEC, '--disallowed-tools',
         'Bash,Edit,Write,Read,Glob,Grep,NotebookEdit,Task,Artifact,WebFetch,WebSearch'],
        input=src, capture_output=True, text=True, timeout=900).stdout.strip()
    if out.startswith('```'):
        out = re.sub(r'^```[a-zA-Z]*\n', '', out)
        out = re.sub(r'\n```\s*$', '', out).strip()
    meta, body = W.parse_text(out) if hasattr(W, 'parse_text') else (None, None)
    if not out.startswith('---') or 'title:' not in out[:600]:
        print('  REJECTED (no front matter)', file=sys.stderr); return False
    if len(body or out) < len(src) * 0.5:
        print('  REJECTED (body shrank)', file=sys.stderr); return False
    open(path, 'w', encoding='utf-8').write(out + '\n')
    return True

if __name__ == '__main__':
    ok = main(sys.argv[1])
    sys.exit(0 if ok else 1)
