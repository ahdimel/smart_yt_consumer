#!/usr/bin/env python3
"""Flatten yt-dlp VTT subtitles into timestamped prose blocks.

Prefers manual captions (clean, punctuated, often speaker-marked) over
auto-generated ones (rolling-window duplication + inline word timings).
"""
import re, sys, os, glob, html

TAG = re.compile(r'<[^>]+>')                       # <00:00:02.000> and <c> tags
CUE = re.compile(r'^(\d{2}:\d{2}:\d{2})\.\d{3}\s+-->')
SPEAKER = re.compile(r'^([A-Z][A-Za-z.\' ]{1,28}):\s+')

# manual captions first: they are punctuated and mark speaker turns with "- "
PREF = ('.en.vtt', '.en-US.vtt', '.en-GB.vtt', '.en-orig.vtt', '.en-en.vtt')


def pick_subs(stem):
    for suffix in PREF:
        if os.path.exists(stem + suffix):
            return stem + suffix, ('auto' if 'orig' in suffix else 'manual')
    hits = sorted(glob.glob(stem + '*.vtt'))
    return (hits[0], 'unknown') if hits else (None, None)


def parse(path):
    """Yield (seconds, text, turn) triples, deduped against the rolling window."""
    out, last, cur = [], None, None
    for line in open(path, encoding='utf-8', errors='replace'):
        line = line.rstrip('\n')
        m = CUE.match(line)
        if m:
            h, mi, s = map(int, m.group(1).split(':'))
            cur = h * 3600 + mi * 60 + s
            continue
        if not line.strip() or line.startswith(('WEBVTT', 'Kind:', 'Language:', 'NOTE')):
            continue
        txt = html.unescape(TAG.sub('', line))
        txt = txt.replace('\u00a0', ' ').strip()
        # a leading "- " in manual captions marks a speaker change: keep that signal
        turn = bool(re.match(r'^-\s', txt))
        txt = re.sub(r'^-\s*', '', txt)
        txt = re.sub(r'\[[^\]]*\]', '', txt)          # [music], [applause]
        txt = re.sub(r'\s+', ' ', txt).strip()        # collapse caption padding
        if not txt or txt == last:                     # rolling-window duplicate
            continue
        last = txt
        out.append((cur if cur is not None else 0, txt, turn))
    return out


def blocks(pairs, window):
    """Group lines into `window`-second blocks, marking speaker turns with |."""
    if not pairs:
        return []
    res, start, buf = [], pairs[0][0], []
    for sec, txt, turn in pairs:
        if sec - start >= window and buf:
            res.append((start, ' '.join(buf)))
            start, buf = sec, []
        buf.append(('| ' + txt) if (turn and buf) else txt)
    if buf:
        res.append((start, ' '.join(buf)))
    return res


def auto_window(duration):
    """Block size only affects timestamp granularity, not token count, so keep it
    fine enough to actually jump to: 60s short, 120s ceiling for long-form."""
    return 120 if duration > 3600 else 60


def run(stem, duration=0, window=None):
    path, kind = pick_subs(stem)
    if not path:
        raise SystemExit('no subtitles found for ' + stem)
    w = window or auto_window(duration)
    bl = blocks(parse(path), w)
    words = sum(len(t.split()) for _, t in bl)
    head = (f'<!-- {os.path.basename(path)} | {kind} captions | '
            f'{words} words | {len(bl)} blocks | {w}s window -->')
    body = '\n'.join(f'[{s//3600:d}:{(s%3600)//60:02d}:{s%60:02d}] {t}' if s >= 3600
                     else f'[{s//60:02d}:{s%60:02d}] {t}' for s, t in bl)
    return head + '\n' + body, words


if __name__ == '__main__':
    text, _ = run(sys.argv[1],
                  int(sys.argv[2]) if len(sys.argv) > 2 else 0,
                  int(sys.argv[3]) if len(sys.argv) > 3 else None)
    print(text)
