#!/usr/bin/env python3
"""Build the model-input bundle: metadata + timestamped transcript + top comments."""
import json, sys, re, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flatten

# engagement noise that carries no correction or dispute
NOISE = re.compile(r'^(first|early|who(\'s| is) here|great video|love your (work|videos)|'
                   r'thanks?( you)?|nice|amazing|wow|w video)\W*$', re.I)


def hms(s):
    s = int(s or 0)
    return f'{s//3600}h{(s%3600)//60:02d}m' if s >= 3600 else f'{s//60}m{s%60:02d}s'


def comments(info, limit=60):
    rows, chan = [], (info.get('channel_id') or '').strip()
    for c in info.get('comments') or []:
        txt = (c.get('text') or '').strip()
        if not txt or c.get('author_is_uploader') or c.get('channel_id') == chan:
            continue
        if len(txt) < 25 or NOISE.match(txt):
            continue
        rows.append({'likes': c.get('like_count') or 0,
                     'text': re.sub(r'\s+', ' ', txt)[:900],
                     'reply': c.get('parent') != 'root'})
    rows.sort(key=lambda r: -r['likes'])
    return rows[:limit]


def build(stem):
    info = json.load(open(stem + '.info.json', encoding='utf-8'))
    dur = info.get('duration') or 0
    tr, words = flatten.run(stem, dur)

    L = ['=== VIDEO ===',
         f"title:    {info.get('title')}",
         f"channel:  {info.get('channel')}",
         f"duration: {hms(dur)}  ({dur} s)",
         f"uploaded: {info.get('upload_date')}",
         f"views:    {(info.get('view_count') or 0):,}",
         f"transcript_words: {words}"]
    desc = re.sub(r'\s*\n\s*', ' | ', (info.get('description') or '')[:600])
    L += [f'description (truncated): {desc}', '', '=== TRANSCRIPT (timestamped) ===', tr]

    cs = comments(info)
    L += ['', f'=== TOP COMMENTS ({len(cs)}, creator + low-signal excluded, by likes) ===']
    L += [f"({c['likes']}){' [reply]' if c['reply'] else ''} {c['text']}" for c in cs]
    return '\n'.join(L), words, info


if __name__ == '__main__':
    text, _, _ = build(sys.argv[1])
    print(text)
