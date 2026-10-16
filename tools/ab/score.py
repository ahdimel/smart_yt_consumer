#!/usr/bin/env python3
"""Score every A/B output: format validity, verdict, fluff, claims, tokens. Prints markdown."""
import json, os, re, sys, glob, statistics as st

REPO = '/Users/ahdimel/code/smart_yt_consumer'
sys.path.insert(0, os.path.join(REPO, 'lib'))
import week as W  # noqa: E402

AB = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, '.cache/ab/run')
VIDEOS = {  # id: (short name, README/W40 reference verdict, reference fluff)
    '45oG6w7bvtM': ('Sandeep (19m listicle)', 'skip', '34%'),
    '504UjcCLleE': ('Prof G (22m)', 'skim', '13%'),
    'BXLGV0Sj0n8': ('Maxinomics (27m)', 'watch', '6%'),
    'SpGKvIbiVWg': ('DW News (18m)', 'skip', '7%'),
    '4l3Sa8ImGFQ': ('Paine (109m lecture)', 'watch all', '<1%'),
}
ARMS = {'A': 'A prod (Opus)', 'B': 'B lean (Opus)', 'D': 'D lean (Sonnet)'}
TS = re.compile(r'`(\d{1,2}:\d{2}(?::\d{2})?)`')


def verdict_label(v):
    m = re.match(r'\*\*(.+?)\*\*', v or '')
    t = (m.group(1) if m else v or '').lower()
    if 'whole' in t: return 'watch all'
    if 'skip' in t: return 'skip'
    if 'skim' in t: return 'skim'
    if 'watch' in t: return 'watch'
    return '?'


def score(md_path):
    raw = open(md_path, encoding='utf-8').read().strip()
    js = json.load(open(md_path[:-3] + '.json')) if os.path.exists(md_path[:-3] + '.json') else {}
    s = re.sub(r'^```[a-zA-Z]*\n|\n```\s*$', '', raw).strip()
    ok = s.startswith('---') and len(s[3:].split('\n---', 1)) == 2 and 'title:' in s[:2000]
    meta, body = W.parse_text(s) if ok else ({}, '')
    fl = meta.get('fluff', '')
    u = js.get('usage', {})
    return {
        'valid': ok,
        'fenced': raw.startswith('```'),
        'verdict': verdict_label(meta.get('verdict')),
        'fluff': fl,
        'fluff_ok': bool(re.fullmatch(r'<?~?\d+(\.\d+)?%', fl)),
        'watchable': meta.get('watchable', ''),
        'watch_ok': bool(re.fullmatch(r'~?\d+ of \d+ min', meta.get('watchable', ''))),
        'comp_ok': bool(re.search(r'→.*words \(\d+(\.\d+)?:1\)', meta.get('compression', ''))),
        'ts': len(set(TS.findall(body))),
        'words': len(body.split()),
        'contest': bool(re.search(r'^## What the comments contest\s*$', body, re.M)),
        'h1': bool(re.search(r'^# ', body, re.M)),
        'in_tok': u.get('input_tokens', 0) + u.get('cache_creation_input_tokens', 0)
                  + u.get('cache_read_input_tokens', 0),
        'out_tok': u.get('output_tokens', 0),
        'think': (u.get('output_tokens_details') or {}).get('thinking_tokens', 0),
        'cost': js.get('total_cost_usd', 0),
        'secs': js.get('duration_ms', 0) / 1000,
        'err': js.get('is_error', not js),
    }


def fluff_num(f):
    m = re.search(r'(\d+(?:\.\d+)?)', f or '')
    return float(m.group(1)) if m else None


rows = {}
for arm in ARMS:
    for p in sorted(glob.glob(os.path.join(AB, arm, '*.md'))):
        vid, run = os.path.basename(p)[:-3].split('.r')
        rows[(arm, vid, run)] = score(p)

print('## Per run\n')
print('| Video | Arm | Run | Valid | Verdict (ref) | Fluff (ref) | Watchable | Claims (ts) | Words | Contest | In tok | Out tok (think) | API-eq $ | Secs |')
print('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
for vid, (name, rv, rf) in VIDEOS.items():
    for arm in ARMS:
        for run in ('1', '2'):
            r = rows.get((arm, vid, run))
            if not r:
                print(f'| {name} | {arm} | {run} | *missing* |' + ' |' * 10); continue
            flags = ('' if r['valid'] else '✗') + (' fenced' if r['fenced'] else '') \
                + ('' if r['fluff_ok'] and r['watch_ok'] and r['comp_ok'] else ' fmt') \
                + (' H1' if r['h1'] else '') + (' ERR' if r['err'] else '')
            print(f"| {name} | {arm} | {run} | {flags or '✓'} | {r['verdict']} ({rv}) | "
                  f"{r['fluff']} ({rf}) | {r['watchable']} | {r['ts']} | {r['words']} | "
                  f"{'✓' if r['contest'] else '✗'} | {r['in_tok']:,} | {r['out_tok']:,} "
                  f"({r['think']:,}) | {r['cost']:.2f} | {r['secs']:.0f} |")

print('\n## Per arm\n')
print('| Arm | Runs | Valid | Verdict = ref | Verdict same both runs | Fluff spread within video (pts, mean) | Claims (mean) | Words (mean) | In tok (mean) | Out tok (mean) | API-eq $ (total) |')
print('|---|---|---|---|---|---|---|---|---|---|---|')
for arm, label in ARMS.items():
    rs = [(k, v) for k, v in rows.items() if k[0] == arm]
    if not rs: continue
    vals = [v for _, v in rs]
    agree = sum(v['verdict'] == VIDEOS[k[1]][1] for k, v in rs)
    stable, spreads = 0, []
    for vid in VIDEOS:
        pair = [rows.get((arm, vid, r)) for r in ('1', '2')]
        if all(pair):
            stable += pair[0]['verdict'] == pair[1]['verdict']
            a, b = fluff_num(pair[0]['fluff']), fluff_num(pair[1]['fluff'])
            if a is not None and b is not None: spreads.append(abs(a - b))
    m = lambda key: st.mean(v[key] for v in vals)
    print(f"| {label} | {len(vals)} | {sum(v['valid'] for v in vals)}/{len(vals)} | "
          f"{agree}/{len(vals)} | {stable}/{len(VIDEOS)} | "
          f"{st.mean(spreads) if spreads else float('nan'):.1f} | {m('ts'):.0f} | {m('words'):.0f} | "
          f"{m('in_tok'):,.0f} | {m('out_tok'):,.0f} | {sum(v['cost'] for v in vals):.2f} |")

print('\n## Between arms, per video (mean of 2 runs)\n')
print('| Video | Fluff A / B / D | Claims A / B / D | Words A / B / D | In tok A / B / D |')
print('|---|---|---|---|---|')
for vid, (name, _, _) in VIDEOS.items():
    cells = []
    for key, fmt in (('fluff', '{:.0f}%'), ('ts', '{:.0f}'), ('words', '{:.0f}'), ('in_tok', '{:,.0f}')):
        parts = []
        for arm in ARMS:
            xs = [rows.get((arm, vid, r)) for r in ('1', '2')]
            xs = [x for x in xs if x]
            nums = [fluff_num(x['fluff']) if key == 'fluff' else x[key] for x in xs]
            nums = [n for n in nums if n is not None]
            parts.append(fmt.format(st.mean(nums)) if nums else '–')
        cells.append(' / '.join(parts))
    print(f'| {name} | ' + ' | '.join(cells) + ' |')
