"""HTML for the user-facing pages. Plain strings and html.escape; no template engine.

The CSP forbids inline script and style, so every page links /static/app.css and nothing else.
M1 carries the minimal versions; the status/history page (§11 L) and the intro page (§5.4) are
filled in by later milestones.
"""
import datetime
from html import escape

PRIVATE = 'Private, invite-only.'
NOT_FOUND = 'Not found.'


def ts(t):
    if t is None:
        return '—'
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def layout(title, body):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{escape(title)}</title><link rel="stylesheet" href="/static/app.css">'
            f'</head><body><main>{body}</main></body></html>')


def bare(line):
    """What strangers see: one line, no app name, no form, no links (§5.4)."""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<title>{escape(line)}</title></head><body><p>{escape(line)}</p></body></html>')


STATUS = {'queued': 'Waiting', 'running': 'Summarizing', 'done': 'Done', 'failed': 'Failed'}


def home(user, jobs, left_day, left_week, message=None):
    note = f'<p class="note">{escape(message)}</p>' if message else ''
    rows = ''.join(
        f'<tr><td>{ts(j["created_at"])}</td><td>{STATUS[j["status"]]}</td></tr>' for j in jobs)
    history = (f'<table><thead><tr><th>Requested</th><th>Status</th></tr></thead>'
               f'<tbody>{rows}</tbody></table>') if jobs else ''
    return layout('Summaries', f"""
<h1>Hi {escape(user['name'])}</h1>
{note}
<form method="post" action="/api/requests">
  <label for="url">YouTube link</label>
  <input id="url" name="url" type="text" inputmode="url" autocomplete="off" required>
  <button type="submit">Summarize</button>
</form>
<p class="quota">{left_day} left today · {left_week} left this week</p>
{history}""")


def placeholder(title, line):
    return layout(title, f'<h1>{escape(title)}</h1><p>{escape(line)}</p><p><a href="/">Continue</a></p>')
