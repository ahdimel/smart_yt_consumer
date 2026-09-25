#!/usr/bin/env python3
"""Build the standing index: one page listing every week, so there is a single
link worth bookmarking even though each week gets its own artifact."""
import sys, os, json, glob, html, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import week as W

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def weeks():
    out = []
    for d in sorted(glob.glob(os.path.join(ROOT, 'out', '*-W*')), reverse=True):
        tag = os.path.basename(d)
        mds = glob.glob(os.path.join(d, '*.md'))
        if not mds:
            continue
        meta = {}
        mp = os.path.join(d, 'meta.json')
        if os.path.exists(mp):
            try:
                meta = json.load(open(mp))
            except Exception:
                pass
        fl, verdicts = [], {}
        for f in mds:
            m, _ = W.parse(f)
            v = (m.get('fluff') or '').strip().strip('~<>%')
            try:
                fl.append(float(v))
            except ValueError:
                pass
            k = (m.get('verdict') or '').replace('*', '').split('.')[0].strip().lower()
            k = 'watch' if k.startswith('watch') else 'skip' if k.startswith('skip') else 'skim'
            verdicts[k] = verdicts.get(k, 0) + 1
        out.append({'tag': tag, 'label': W.week_label(tag), 'n': len(mds),
                    'url': meta.get('artifact_url', ''),
                    'fluff': round(sum(fl) / len(fl)) if fl else None,
                    'v': verdicts})
    return out


def render(ws):
    rows = []
    for w in ws:
        v = w['v']
        chips = ''.join(
            f'<span class="chip {k}">{v[k]} {k}</span>'
            for k in ('watch', 'skim', 'skip') if v.get(k))
        fluff = f"{w['fluff']}% avg fluff" if w['fluff'] is not None else '&mdash;'
        inner = (f'<div class="wk"><div class="wtop"><span class="wlab">{w["label"]}</span>'
                 f'<span class="wn">{w["n"]} video{"s" if w["n"] != 1 else ""}</span></div>'
                 f'<div class="wmeta"><span class="fl">{fluff}</span>{chips}</div></div>')
        rows.append(f'<a class="row" href="{w["url"]}">{inner}</a>' if w['url']
                    else f'<div class="row dead">{inner}'
                         f'<span class="warn">not published &mdash; check drain.log</span></div>')
    return TPL.replace('{{ROWS}}', '\n'.join(rows)) \
              .replace('{{TOTAL}}', str(sum(w['n'] for w in ws))) \
              .replace('{{WEEKS}}', str(len(ws))) \
              .replace('{{UPDATED}}', datetime.date.today().strftime('%-d %B %Y'))


TPL = '''<title>Video Digest Index</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
  :root{--paper:#f6f7f9;--card:#fff;--ink:#17202c;--body:#2c3846;--muted:#63707f;
    --rule:#dde2e8;--accent:#0d6f7d;--accent-soft:#e3f0f1;--warn:#a04e39;}
  @media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
    --paper:#111721;--card:#18202b;--ink:#e9edf2;--body:#c3cdd8;--muted:#8593a3;
    --rule:#2a3542;--accent:#4cbccb;--accent-soft:#16333a;--warn:#d78a72;}}
  :root[data-theme="dark"]{--paper:#111721;--card:#18202b;--ink:#e9edf2;--body:#c3cdd8;
    --muted:#8593a3;--rule:#2a3542;--accent:#4cbccb;--accent-soft:#16333a;--warn:#d78a72;}
  *{box-sizing:border-box}
  body{background:var(--paper);color:var(--body);margin:0;
    font-family:"Newsreader",Georgia,serif;font-size:1.0625rem;line-height:1.6}
  .wrap{max-width:34rem;margin:0 auto;padding-inline:20px;padding-block:3rem 4rem}
  .eyebrow{font-family:"IBM Plex Mono",monospace;font-size:.68rem;letter-spacing:.11em;
    text-transform:uppercase;color:var(--accent);font-weight:600;margin:0 0 .6rem}
  h1{font-size:clamp(1.9rem,6vw,2.5rem);line-height:1.1;font-weight:600;color:var(--ink);
    margin:0 0 .7rem;letter-spacing:-.017em}
  .dek{font-family:"IBM Plex Mono",monospace;font-size:.72rem;color:var(--muted);
    letter-spacing:.04em;margin:0 0 2.5rem}
  .row{display:block;text-decoration:none;color:inherit;background:var(--card);
    border:1px solid var(--rule);border-left:3px solid var(--accent);border-radius:3px;
    padding:1rem 1.1rem;margin-bottom:.7rem;transition:border-color .15s}
  .row:hover,.row:focus-visible{border-left-color:var(--ink)}
  .row.dead{border-left-color:var(--warn);opacity:.85}
  .wtop{display:flex;justify-content:space-between;align-items:baseline;gap:1rem}
  .wlab{font-size:1.05rem;font-weight:600;color:var(--ink)}
  .wn{font-family:"IBM Plex Mono",monospace;font-size:.7rem;color:var(--muted);white-space:nowrap}
  .wmeta{display:flex;flex-wrap:wrap;gap:.4rem .6rem;margin-top:.5rem;align-items:center}
  .fl{font-family:"IBM Plex Mono",monospace;font-size:.7rem;color:var(--accent);
    background:var(--accent-soft);padding:.15em .45em;border-radius:2px}
  .chip{font-family:"IBM Plex Mono",monospace;font-size:.66rem;color:var(--muted)}
  .warn{display:block;margin-top:.5rem;font-family:"IBM Plex Mono",monospace;
    font-size:.66rem;color:var(--warn)}
  .foot{margin-top:2.5rem;padding-top:1.3rem;border-top:1px solid var(--rule);
    font-family:"IBM Plex Mono",monospace;font-size:.67rem;color:var(--muted);line-height:1.7}
</style>
<div class="wrap">
  <p class="eyebrow">smart_yt_consumer</p>
  <h1>Video Digest Index</h1>
  <p class="dek">{{WEEKS}} weeks &middot; {{TOTAL}} videos &middot; updated {{UPDATED}}</p>
  {{ROWS}}
  <p class="foot">Bookmark this page &mdash; each week gets its own artifact, and this is the
  standing link that always lists them.<br>
  A week shown without a link never published; the reason is in
  ~/Library/Logs/smart_yt_consumer/drain.log</p>
</div>'''

if __name__ == '__main__':
    ws = weeks()
    out = os.path.join(ROOT, 'out', 'index.html')
    open(out, 'w', encoding='utf-8').write(render(ws))
    print(out)
    for w in ws:
        print(f"  {w['tag']}  {w['n']:>2} videos  {w['url'] or 'NOT PUBLISHED'}")
