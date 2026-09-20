#!/usr/bin/env python3
"""Normalise a raw summary: strip any code fence, verify front matter, stamp the time.

Exits non-zero if the output does not look like a summary, so drain can requeue.
"""
import re, sys, datetime

raw, dst = sys.argv[1], sys.argv[2]
s = open(raw, encoding='utf-8').read().strip()

# models often wrap the whole file in ```markdown ... ```
if s.startswith('```'):
    s = re.sub(r'^```[a-zA-Z]*\n', '', s)
    s = re.sub(r'\n```\s*$', '', s)
    s = s.strip()

if not s.startswith('---'):
    sys.exit('no front matter')
head = s[3:].split('\n---', 1)
if len(head) < 2 or 'title:' not in head[0]:
    sys.exit('front matter missing title')

s = re.sub(r'^added:.*$', 'added: ' + datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
           s, count=1, flags=re.M)
open(dst, 'w', encoding='utf-8').write(s + '\n')
