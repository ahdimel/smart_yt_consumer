"""Notification email: one per finished job, title and link only (D1).

M1 has the outbox and the exactly-once delivery; the Resend client and the final copy come in
M3. With no mailer configured, finished jobs simply stay `pending` until one is.
"""
import datetime
import html
from typing import Protocol

from . import codes


class Mailer(Protocol):
    def send(self, to: str, subject: str, html_body: str, text_body: str) -> str:
        """Return 'sent', 'retry' (transient, e.g. 5xx) or 'failed' (permanent, e.g. 4xx)."""


def _date(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%-d %B %Y')


def compose(job, summary, origin):
    """(subject, html, text) for a finished job. Nothing from the summary but its title."""
    if job['status'] == 'done' and summary is not None:
        title = summary['title']
        link = f'{origin}/s/{job["public_id"]}'
        until = _date(summary['expires_at'])
        subject = f'Summary: {title}'
        text = f'{title}\n\nRead the summary: {link}\n\nAvailable until {until}.\n'
        body = (f'<p><strong>{html.escape(title)}</strong></p>'
                f'<p><a href="{html.escape(link)}">Read the summary</a></p>'
                f'<p>Available until {until}.</p>')
        return subject, body, text
    reason = codes.CODES.get(job['error_code'], codes.Code(1, message='Something went wrong.')).message
    subject = "Couldn't summarize your video"
    text = f'{reason}\n\nThis didn\'t count against your limit.\n'
    body = f'<p>{html.escape(reason)}</p><p>This didn\'t count against your limit.</p>'
    return subject, body, text


def deliver_pending(conn, mailer, origin):
    """Send every pending email once. Safe to call concurrently: each job is claimed by a
    conditional update before sending, so two callers can't both send it."""
    if mailer is None:
        return
    ids = [r['id'] for r in conn.execute("SELECT id FROM jobs WHERE email_status = 'pending'")]
    for jid in ids:
        claimed = conn.execute(
            "UPDATE jobs SET email_status = 'sending' WHERE id = ? AND email_status = 'pending'",
            (jid,)).rowcount
        if not claimed:
            continue
        job = conn.execute(
            'SELECT j.*, u.email FROM jobs j JOIN users u ON u.id = j.user_id WHERE j.id = ?',
            (jid,)).fetchone()
        summary = conn.execute('SELECT * FROM summaries WHERE video_id = ?',
                               (job['video_id'],)).fetchone()
        try:
            outcome = mailer.send(job['email'], *compose(job, summary, origin))
        except Exception:
            outcome = 'retry'
        status = {'sent': 'sent', 'failed': 'failed'}.get(outcome, 'pending')
        conn.execute('UPDATE jobs SET email_status = ? WHERE id = ?', (status, jid))
