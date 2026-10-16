"""Notification email: one per finished job, title and link only (D1, §11 H).

The outbox is `jobs.email_status`: `pending` → `sending` (a claim, so concurrent deliveries
can't both send) → `sent` or `failed`. A transient failure (5xx, 429, timeout, no answer) puts
the job back to `pending` with a backoff; a permanent one (any other 4xx) fails it at once, so
a bad address or a revoked key can't become a retry storm (H5). A `sending` row left behind by
a process that died mid-send is reset after STALE_SENDING. Resend's Idempotency-Key, one per
job, keeps that reset from sending twice if the first send had in fact gone through.

Logs carry the job ID, the outcome and Resend's HTTP status. Never an address or a title.
"""
import datetime
import html
import json
import logging
import urllib.error
import urllib.request
from typing import Protocol

from . import codes

log = logging.getLogger('server')

BACKOFF = (60, 5 * 60, 15 * 60, 60 * 60, 3 * 3600)   # wait after attempt n, n = 1..5
MAX_ATTEMPTS = len(BACKOFF) + 1                       # about 4.5 hours of trying in all
STALE_SENDING = 10 * 60
LOOP_SECONDS = 30
TIMEOUT = 15


class Mailer(Protocol):
    def send(self, to: str, subject: str, html_body: str, text_body: str,
             key: str) -> str:
        """Return 'sent', 'retry' (transient, e.g. 5xx) or 'failed' (permanent, e.g. 4xx).
        `key` is the same for every attempt at one email."""


class ResendMailer:
    """Resend's HTTP API over plain HTTPS (D9). Stdlib only: one POST per email."""

    def __init__(self, api_key, sender, reply_to, base='https://api.resend.com'):
        self.api_key, self.sender, self.reply_to = api_key, sender, reply_to
        self.url = base.rstrip('/') + '/emails'
        self.last_status = None

    def __repr__(self):
        return f'ResendMailer({self.url!r})'

    def send(self, to, subject, html_body, text_body, key):
        msg = {'from': self.sender, 'to': [to], 'subject': subject, 'html': html_body,
               'text': text_body}
        # Reply-To equal to To is a phishing signal (rspamd's REPLYTO_EQ_TO_ADDR). Together with
        # a link to the young desloppify.ahdimel.com, it got the owner's own mail to hello@
        # rejected by Proton ("554 5.7.1 rejected by rspamd filter", 2026-10-16); either alone
        # was delivered. Replying to yourself is pointless, so leave the header off.
        if self.reply_to and self.reply_to.strip().lower() != to.strip().lower():
            msg['reply_to'] = self.reply_to
        body = json.dumps(msg).encode()
        req = urllib.request.Request(self.url, data=body, method='POST', headers={
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'Idempotency-Key': key,
            'User-Agent': 'desloppify/1',
        })
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                self.last_status = r.status
        except urllib.error.HTTPError as e:
            self.last_status = e.code
        except OSError:                       # URLError, timeouts, refused connections
            self.last_status = None
            return 'retry'
        return classify(self.last_status)


def classify(status):
    if 200 <= status < 300:
        return 'sent'
    # 429: Resend's rate limit. 409: another request with this idempotency key is in flight.
    if status >= 500 or status in (408, 409, 429):
        return 'retry'
    return 'failed'


def from_settings(settings):
    if not settings.resend_api_key:
        return None
    if not settings.public_origin:
        # The retry loop has no request to take an origin from; links would be relative.
        raise ValueError('RESEND_API_KEY is set but PUBLIC_ORIGIN is not')
    return ResendMailer(settings.resend_api_key, settings.mail_from, settings.mail_reply_to,
                        settings.resend_api_url)


def _date(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%-d %B %Y')


def _when(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime(
        '%-d %B %Y at %H:%M UTC')


def _html(*paragraphs):
    ps = ''.join(f'<p>{p}</p>' for p in paragraphs)
    return (f'<!doctype html><html><body style="font-family:-apple-system,Segoe UI,sans-serif;'
            f'font-size:16px;line-height:1.5;color:#17202c">{ps}</body></html>')


def compose(job, summary, origin):
    """(subject, html, text) for a finished job. Nothing from the summary but its title (D1)."""
    if job['status'] == 'done' and summary is not None:
        title = summary['title']
        link = f'{origin}/s/{job["public_id"]}'
        until = _date(summary['expires_at'])
        subject = f'Summary: {title}'
        text = f'{title}\n\nRead the summary: {link}\n\nAvailable until {until}.\n'
        body = _html(f'<strong>{html.escape(title)}</strong>',
                     f'<a href="{html.escape(link)}">Read the summary</a>',
                     f'Available until {until}.')
        return subject, body, text
    # A failed job has no title: the worker reports none, and the server never fetches one.
    # The time of the request is what tells the friend which video this was.
    reason = codes.CODES.get(job['error_code'], codes.Code(1, message='Something went wrong.')).message
    sent = _when(job['created_at'])
    subject = "Couldn't summarize your video"
    first = f"Your video sent on {sent} couldn't be summarized."
    text = f"{first}\n\n{reason}\n\nThis didn't count against your limit.\n"
    body = _html(html.escape(first), html.escape(reason),
                 "This didn't count against your limit.")
    return subject, body, text


def reset_stale(conn, now):
    """`sending` rows whose sender died mid-send go back to `pending`."""
    return conn.execute(
        "UPDATE jobs SET email_status = 'pending' "
        "WHERE email_status = 'sending' AND (email_claimed_at IS NULL OR email_claimed_at < ?)",
        (now - STALE_SENDING,)).rowcount


def deliver_pending(conn, mailer, origin, now):
    """Send every email that is due, once each. Safe to call concurrently: each job is claimed
    by a conditional update before sending, so two callers can't both send it."""
    if mailer is None:
        return
    reset_stale(conn, now)
    ids = [r['id'] for r in conn.execute(
        "SELECT id FROM jobs WHERE email_status = 'pending' "
        'AND (email_not_before IS NULL OR email_not_before <= ?) ORDER BY id', (now,))]
    for jid in ids:
        claimed = conn.execute(
            "UPDATE jobs SET email_status = 'sending', email_claimed_at = ?, "
            'email_attempts = email_attempts + 1 '
            "WHERE id = ? AND email_status = 'pending'", (now, jid)).rowcount
        if not claimed:
            continue
        job = conn.execute(
            'SELECT j.*, u.email FROM jobs j JOIN users u ON u.id = j.user_id WHERE j.id = ?',
            (jid,)).fetchone()
        summary = conn.execute('SELECT * FROM summaries WHERE video_id = ?',
                               (job['video_id'],)).fetchone()
        try:
            outcome = mailer.send(job['email'], *compose(job, summary, origin),
                                  key=f'job-{jid}-{job["created_at"]}')
        except Exception as e:
            log.warning('mail job=%s error=%s', jid, type(e).__name__)
            outcome = 'retry'
        n = job['email_attempts']
        if outcome not in ('sent', 'failed'):
            outcome = 'retry'
        if outcome == 'retry' and n >= MAX_ATTEMPTS:
            outcome = 'failed'
        if outcome == 'retry':
            conn.execute("UPDATE jobs SET email_status = 'pending', email_not_before = ? "
                         'WHERE id = ?', (now + BACKOFF[n - 1], jid))
        else:
            conn.execute('UPDATE jobs SET email_status = ?, email_not_before = NULL WHERE id = ?',
                         ('sent' if outcome == 'sent' else 'failed', jid))
        log.info('mail job=%s attempt=%s outcome=%s http=%s', jid, n, outcome,
                 getattr(mailer, 'last_status', None))
