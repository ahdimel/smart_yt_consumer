"""The summary page (/s/<public_id>), rendered from stored markdown on every request.

Rendering reuses lib/week.py (the renderer M0 made safe, tests/test_render.py), so a template
change applies to old summaries too. The CSP forbids inline script and style, so the page links
/static/summary.css and /static/summary.js and nothing else, not even web fonts.
"""
import datetime
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import week  # noqa: E402

TEMPLATE = Path(__file__).with_name('summary.html').read_text(encoding='utf-8')
# week.inline() escapes everything before it adds markup, so the only <span class="ts"> in its
# output are the ones it made itself, around a validated timestamp.
CHIP = re.compile(r'<span class="ts">(\d{1,2}(?::\d{2}){1,2})</span>')
VIDEO_ID = re.compile(r'[A-Za-z0-9_-]{11}\Z')


def seconds(stamp):
    n = 0
    for part in stamp.split(':'):
        n = n * 60 + int(part)
    return n


def link_chips(body, video_id):
    """Timestamp chips become links into the video at that moment (§11 I7)."""
    if not VIDEO_ID.match(video_id):
        return body
    return CHIP.sub(
        lambda m: (f'<a class="ts" href="https://www.youtube.com/watch?v={video_id}'
                   f'&amp;t={seconds(m.group(1))}s">{m.group(1)}</a>'), body)


def date(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%-d %B %Y')


def page(md, video_id, expires_at):
    meta, body = week.parse_text(md)
    title = meta.get('title') or 'Summary'
    art = link_chips(week.article(video_id, meta, body, 'summary'), video_id)
    return (TEMPLATE.replace('{{TITLE}}', html.escape(title))
                    .replace('{{UNTIL}}', date(expires_at))
                    .replace('{{ARTICLE}}', art))


def gone():
    """The expired page. No title, nothing about which video it was (§11 I11)."""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Expired</title><link rel="stylesheet" href="/static/summary.css"></head>'
            '<body><div class="wrap"><p>This summary has expired. Summaries are kept for '
            '30 days.</p></div></body></html>')
