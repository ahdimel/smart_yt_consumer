#!/usr/bin/env python3
"""Find summaries whose metric fields aren't canonical, and repair them."""
import sys, os, re, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import week as W, repair

PCT = re.compile(r'^[~<>]?\s*\d+(\.\d+)?%$')
WATCH = re.compile(r'^[~<>]?\s*[\d.]+\s+of\s+[\d.]+\s+min$')


def malformed(meta):
    why = []
    if not PCT.match((meta.get('fluff') or '').strip()):
        why.append('fluff')
    if not WATCH.match((meta.get('watchable') or '').strip()):
        why.append('watchable')
    if not (meta.get('verdict') or '').lstrip().startswith('**'):
        why.append('verdict')
    return why


if __name__ == '__main__':
    wdir = sys.argv[1]
    targets = []
    for f in sorted(glob.glob(os.path.join(wdir, '*.md'))):
        meta, _ = W.parse(f)
        why = malformed(meta)
        if why:
            targets.append((f, why))
    print(f'{len(targets)} of {len(glob.glob(os.path.join(wdir, "*.md")))} need repair')
    for f, why in targets:
        print(f'  {os.path.basename(f):<20} {",".join(why):<28}', end='', flush=True)
        try:
            print('repaired' if repair.main(f) else 'FAILED')
        except Exception as e:
            print('ERROR', e)
