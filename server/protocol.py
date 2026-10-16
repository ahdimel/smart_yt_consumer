"""The worker's side of the queue: claim, complete, fail (proposal §5.3, §11 E).

A claim hands out a lease with a random `lease_id`. `complete` and `fail` must quote it, so a
worker whose lease expired (the Mac slept) and was re-leased can't overwrite the newer attempt.
"""
import re
import secrets

from . import db, urls
from .codes import CODES
from .config import DAY, RETENTION

USAGE_KEYS = {             # claude -p JSON `usage` → jobs column
    'input_tokens': 'input_tokens',
    'cache_creation_input_tokens': 'cache_write_tokens',
    'cache_read_input_tokens': 'cache_read_tokens',
    'output_tokens': 'output_tokens',
}


class ProtocolError(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status, self.code = status, code


def tokens_last_day(conn, now):
    return conn.execute(
        'SELECT COALESCE(SUM(input_tokens + cache_write_tokens + cache_read_tokens + output_tokens), 0) '
        'FROM jobs WHERE usage_at > ?', (now - DAY,)).fetchone()[0]


def claim(conn, now, lease_seconds, version=None):
    """The next job's payload, or None (nothing claimable, paused, or over the token ceiling)."""
    with db.tx(conn):
        conn.execute('UPDATE worker SET last_seen = ?, version = COALESCE(?, version) WHERE id = 1',
                     (now, version))
        s = db.settings(conn)
        if s['paused']:
            return None
        ceiling = s['global_daily_token_ceiling']
        if ceiling is not None and tokens_last_day(conn, now) >= ceiling:
            return None
        job = conn.execute(
            """SELECT j.*, u.max_minutes FROM jobs j JOIN users u ON u.id = j.user_id
               WHERE j.coalesced_with IS NULL
                 AND ((j.status = 'queued' AND (j.not_before IS NULL OR j.not_before <= ?))
                      OR (j.status = 'running' AND j.lease_until < ?))
               ORDER BY j.created_at, j.id LIMIT 1""", (now, now)).fetchone()
        if job is None:
            return None
        lease_id = secrets.token_urlsafe(16)
        lease_until = now + lease_seconds
        conn.execute(
            """UPDATE jobs SET status = 'running', attempts = attempts + 1, lease_id = ?,
                      lease_until = ?, not_before = NULL WHERE id = ?""",
            (lease_id, lease_until, job['id']))
        return {
            'job_id': job['id'],
            'lease_id': lease_id,
            'lease_until': lease_until,
            'attempt': job['attempts'] + 1,
            'video_id': job['video_id'],
            'url': urls.canonical(job['video_id']),
            'max_minutes': job['max_minutes'],
        }


def _usage(conn, job_id, usage, cost_usd, model, now):
    usage = usage if isinstance(usage, dict) else {}
    sets, args = [], []
    for src, col in USAGE_KEYS.items():
        sets.append(f'{col} = {col} + ?')
        args.append(_count(usage.get(src)))
    cost = cost_usd if isinstance(cost_usd, (int, float)) and cost_usd >= 0 else 0
    sets += ['cost_usd = cost_usd + ?', 'usage_at = ?', 'model = COALESCE(?, model)']
    args += [float(cost), now, model if isinstance(model, str) and len(model) < 100 else None]
    conn.execute(f'UPDATE jobs SET {", ".join(sets)} WHERE id = ?', (*args, job_id))


def _count(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def _leased(conn, job_id, lease_id, done_status):
    """The job, if this lease may report on it. Returns (job, replay) where replay means the
    same lease already reported this outcome (a retried request): answer 200, change nothing."""
    job = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
    if job is None:
        raise ProtocolError(404, 'no_such_job')
    if not isinstance(lease_id, str) or job['lease_id'] != lease_id:
        raise ProtocolError(409, 'lease_mismatch')
    if job['status'] == done_status:
        return job, True
    if job['status'] != 'running':
        raise ProtocolError(409, 'not_running')
    return job, False


def front_matter(md):
    """(title, verdict) from a summary's front matter, or None if it isn't a summary.

    Same acceptance rule as lib/clean.py: front matter delimited by `---`, with a title.
    """
    if not isinstance(md, str) or not md.startswith('---\n'):
        return None
    head, sep, _ = md[4:].partition('\n---')
    if not sep:
        return None
    meta = {}
    for line in head.splitlines():
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s?(.*)$', line)
        if m:
            meta[m.group(1)] = m.group(2).strip().strip('"\'').strip()
    if not meta.get('title'):
        return None
    return meta['title'], meta.get('verdict') or None


def complete(conn, job_id, body, now):
    with db.tx(conn):
        job, replay = _leased(conn, job_id, body.get('lease_id'), 'done')
        if replay:
            return
        fm = front_matter(body.get('md'))
        if fm is None:
            raise ProtocolError(422, 'invalid_output')   # job stays leased; worker reports it
        title, verdict = fm
        _usage(conn, job['id'], body.get('usage'), body.get('cost_usd'), body.get('model'), now)
        conn.execute(
            """INSERT INTO summaries (video_id, md, title, verdict, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (video_id) DO UPDATE SET md = excluded.md, title = excluded.title,
                 verdict = excluded.verdict, created_at = excluded.created_at,
                 expires_at = excluded.expires_at""",
            (job['video_id'], body['md'], title, verdict, now, now + RETENTION))
        _finish(conn, job['id'], 'done', None, now)


def fail(conn, job_id, body, now):
    code = body.get('error_code')
    policy = CODES.get(code)
    if policy is None:
        raise ProtocolError(422, 'unknown_error_code')
    with db.tx(conn):
        job, replay = _leased(conn, job_id, body.get('lease_id'), 'failed')
        if replay:
            return
        _usage(conn, job['id'], body.get('usage'), body.get('cost_usd'), body.get('model'), now)
        if job['attempts'] < policy.max_attempts:
            delay = policy.backoff[min(job['attempts'], len(policy.backoff)) - 1]
            conn.execute(
                """UPDATE jobs SET status = 'queued', not_before = ?, lease_id = NULL,
                          lease_until = NULL, error_code = ? WHERE id = ?""",
                (now + delay, code, job['id']))
        else:
            _finish(conn, job['id'], 'failed', code, now)


def _finish(conn, job_id, status, code, now):
    """Close a job and everything coalesced onto it; each gets its own email (D4, D5)."""
    conn.execute(
        """UPDATE jobs SET status = ?, error_code = ?, finished_at = ?, lease_until = NULL,
                  email_status = 'pending'
           WHERE id = ? OR (coalesced_with = ? AND status = 'queued')""",
        (status, code, now, job_id, job_id))
