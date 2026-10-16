"""Submitting a request: dedupe, cache, coalesce, quota (proposal §7, §11 C–D).

Everything runs inside one BEGIN IMMEDIATE transaction, so concurrent submissions see each
other's jobs and quota can't be overspent by a race (C11).
"""
import secrets

from . import db
from .config import DAY, WEEK

# Jobs that consume tokens: not cache hits, not riding on another job, not failed.
COUNTED = """status IN ('queued', 'running', 'done') AND cache_hit = 0
             AND coalesced_with IS NULL"""


class Rejected(Exception):
    def __init__(self, status, code, message, retry_at=None):
        super().__init__(code)
        self.status, self.code, self.message, self.retry_at = status, code, message, retry_at


def new_public_id():
    return secrets.token_urlsafe(16)          # 128 bits, unrelated to row id or time


def _retry_at(times, limit, window):
    """When the oldest blocking job leaves the rolling window. `times` ascending."""
    return times[max(len(times) - limit, 0)] + window


def check_quota(conn, user, now):
    for limit, window, code, what in (
        (user['daily_limit'], DAY, 'quota_daily', 'today'),
        (user['weekly_limit'], WEEK, 'quota_weekly', 'this week'),
    ):
        times = [r[0] for r in conn.execute(
            f'SELECT created_at FROM jobs WHERE user_id = ? AND created_at > ? AND {COUNTED} '
            'ORDER BY created_at', (user['id'], now - window))]
        if len(times) >= limit:
            raise Rejected(429, code, f"You've used all {limit} of your requests {what}.",
                           _retry_at(times, limit, window))

    limit = db.settings(conn)['global_daily_limit']
    times = [r[0] for r in conn.execute(
        f'SELECT created_at FROM jobs WHERE created_at > ? AND {COUNTED} ORDER BY created_at',
        (now - DAY,))]
    if len(times) >= limit:
        raise Rejected(429, 'busy', 'The summarizer is at its daily limit. Try again later.',
                       _retry_at(times, limit, DAY))


def _insert(conn, user, video_id, now, **cols):
    cols = {'public_id': new_public_id(), 'user_id': user['id'], 'video_id': video_id,
            'created_at': now, **cols}
    keys = ', '.join(cols)
    marks = ', '.join('?' * len(cols))
    jid = conn.execute(f'INSERT INTO jobs ({keys}) VALUES ({marks})', tuple(cols.values())).lastrowid
    return conn.execute('SELECT * FROM jobs WHERE id = ?', (jid,)).fetchone()


def submit(conn, user, video_id, now):
    """(job row, created). Raises Rejected."""
    with db.tx(conn):
        if db.settings(conn)['paused']:
            raise Rejected(503, 'paused', 'Summaries are paused for now. Try again later.')

        # C12: the same request again returns the job already in flight.
        same = conn.execute(
            "SELECT * FROM jobs WHERE user_id = ? AND video_id = ? AND status IN ('queued', 'running') "
            'ORDER BY created_at LIMIT 1', (user['id'], video_id)).fetchone()
        if same:
            return same, False

        # D1: a live cached summary is served at once and costs nothing.
        cached = conn.execute('SELECT 1 FROM summaries WHERE video_id = ? AND expires_at > ?',
                              (video_id, now)).fetchone()
        if cached:
            return _insert(conn, user, video_id, now, status='done', cache_hit=1,
                           finished_at=now, email_status='pending'), True

        # D4: someone else's job for this video is in flight; ride on it.
        primary = conn.execute(
            "SELECT id FROM jobs WHERE video_id = ? AND status IN ('queued', 'running') "
            'AND coalesced_with IS NULL ORDER BY created_at LIMIT 1', (video_id,)).fetchone()
        if primary:
            return _insert(conn, user, video_id, now, status='queued',
                           coalesced_with=primary['id']), True

        check_quota(conn, user, now)
        return _insert(conn, user, video_id, now, status='queued'), True


def remaining(conn, user, now):
    """Requests left today and this week, for the home page."""
    def used(window):
        return conn.execute(
            f'SELECT COUNT(*) FROM jobs WHERE user_id = ? AND created_at > ? AND {COUNTED}',
            (user['id'], now - window)).fetchone()[0]
    return (max(user['daily_limit'] - used(DAY), 0), max(user['weekly_limit'] - used(WEEK), 0))
