"""HTML for the user-facing pages. Plain strings and html.escape; no template engine.

The CSP forbids inline script and style, so pages link /static/app.css and, where they need
script, a file under /static/. The words of the intro page live in intro.py.
"""
import datetime
from html import escape
from string import Template

from . import intro

PRIVATE = 'Private, invite-only.'
NOT_FOUND = 'Not found.'
APP_NAME = 'desloppify'


def ts(t):
    if t is None:
        return '—'
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def layout(title, body, scripts=()):
    """A signed-in page. Strangers never get one, so the manifest and icons are linked here only."""
    tags = ''.join(f'<script src="/static/{s}" defer></script>' for s in scripts)
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{escape(title)}</title><link rel="stylesheet" href="/static/app.css">'
            '<link rel="manifest" href="/manifest.webmanifest">'
            '<link rel="icon" href="/static/icon-192.png">'
            '<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">'
            '<meta name="theme-color" content="#2a5db0">'
            f'{tags}</head><body><main>{body}</main></body></html>')


def bare(line):
    """What strangers see: one line, no app name, no form, no links (§5.4)."""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<title>{escape(line)}</title></head><body><p>{escape(line)}</p></body></html>')


STATUS = {'queued': 'Waiting', 'running': 'Summarizing', 'done': 'Done', 'failed': 'Failed'}


def paste_box():
    """The paste box. paste.js reveals the button, which reads the clipboard and submits."""
    return """
<form method="post" action="/api/requests" id="paste-form">
  <label for="url">YouTube link</label>
  <input id="url" name="url" type="text" inputmode="url" autocomplete="off" required>
  <button type="submit">Summarize</button>
  <button type="button" id="paste" hidden>Paste and summarize</button>
</form>
<p id="paste-hint" class="note" role="status" hidden></p>"""


def home(user, jobs, left_day, left_week, message=None):
    note = f'<p class="note">{escape(message)}</p>' if message else ''
    rows = ''.join(
        f'<tr><td>{ts(j["created_at"])}</td><td>{STATUS[j["status"]]}</td></tr>' for j in jobs)
    history = (f'<table><thead><tr><th>Requested</th><th>Status</th></tr></thead>'
               f'<tbody>{rows}</tbody></table>') if jobs else ''
    return layout('Summaries', f"""
<h1>Hi {escape(user['name'])}</h1>
{note}
{paste_box()}
<p class="quota">{left_day} left today · {left_week} left this week</p>
{history}
<p><a href="/about">How to use this, and what I can see</a></p>""", scripts=['paste.js'])


def problem(message):
    """A refused browser form: a sentence and a way back, never a JSON body."""
    return layout('Not sent', f'<h1>Not sent</h1><p>{escape(message)}</p>'
                              '<p><a href="/">Back to your page</a></p>')


def add():
    """The bookmarklet's landing page. add.js reads the link from #fragment and submits it."""
    return layout('Summarize', """
<h1>Summarize</h1>
<p id="add-status" role="status">Sending…</p>
<noscript><p>This page needs JavaScript to send the video. You can paste the link on
<a href="/">your page</a> instead.</p></noscript>
<p><a href="/">Your page</a> · <button type="button" id="add-close" hidden>Close this tab</button></p>""",
                  scripts=['add.js'])


# ── the intro page (§5.4) ─────────────────────────────────────────────────

def platform(user_agent):
    """'android', 'ios' or 'desktop', from the User-Agent (§11 M5).

    iPads ask for the desktop site by default and say "Macintosh"; they get the desktop block
    first, and their own one sits a tap away.
    """
    ua = user_agent or ''
    if 'Android' in ua:
        return 'android'
    if any(k in ua for k in ('iPhone', 'iPad', 'iPod')):
        return 'ios'
    return 'desktop'


def length(minutes):
    if minutes % 60 == 0:
        h = minutes // 60
        return f'{h} hour' + ('s' if h != 1 else '')
    return f'{minutes} minutes'


def bookmarklet(origin):
    return ("javascript:void(open('" + origin + "/add#'+encodeURIComponent(location.href)))")


def intro_page(user, origin, user_agent, setup_first, sender):
    """/welcome (setup_first) or /about. Limits come from the user's own row (§11 M6)."""
    values = {'daily': user['daily_limit'], 'weekly': user['weekly_limit'],
              'max_length': length(user['max_minutes']),
              'bookmarklet': escape(bookmarklet(origin)), 'sender': escape(sender)}

    def fill(fragment):
        return Template(fragment).safe_substitute(values)

    mine = platform(user_agent)
    order = [mine] + [p for p in intro.SETUP if p != mine]
    blocks = ''.join(
        f'<details class="setup" id="setup-{p}"{" open" if p == mine else ""}>'
        f'<summary>{escape(intro.SETUP[p][0])}</summary>{fill(intro.SETUP[p][1])}</details>'
        for p in order)
    setup = f'<section id="setup">{fill(intro.SETUP_HEADING)}{blocks}</section>'
    sections = ''.join(f'<section id="{key}">{fill(html)}</section>' for key, html in intro.INTRO)
    title = 'Welcome' if setup_first else 'About'
    head = f'<h1>{escape(title)}, {escape(user["name"])}</h1>'
    body = (head + setup + sections) if setup_first else (head + sections + setup)
    return layout(title, body + '<p><a href="/">Go to your page</a></p>')
