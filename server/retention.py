"""The retention purge (D2, §11 K1–K2): content goes 30 days after it was made.

`summaries` rows go once `expires_at` has passed, and `jobs.video_id` is nulled once a finished
job's 30 days are up. Queued and running jobs keep theirs, however old: the worker needs it, and
a job waits as long as the Mac is off. Usage columns are never touched, so the admin view reads
the same after a purge (K1).

`/s/<id>` and the cache lookup already treat expired rows as gone; this makes them gone. It runs
in one BEGIN IMMEDIATE transaction, so a submit sees the database either before or after it
(K2). db.connect() turns on secure_delete, so deleted rows are zeroed in the file, and the WAL
is truncated after each pass, so no old copy of a page outlives the purge on disk.
"""
import logging

from . import db
from .config import RETENTION

log = logging.getLogger('server')

LOOP_SECONDS = 3600


def purge(conn, now):
    """(summaries deleted, jobs unlinked). Idempotent."""
    with db.tx(conn):
        summaries = conn.execute('DELETE FROM summaries WHERE expires_at <= ?', (now,)).rowcount
        jobs = conn.execute(
            "UPDATE jobs SET video_id = NULL WHERE video_id IS NOT NULL "
            "AND status IN ('done', 'failed') AND COALESCE(finished_at, created_at) + ? <= ?",
            (RETENTION, now)).rowcount
    # Busy readers make this a partial checkpoint, not an error; the next pass finishes it.
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    if summaries or jobs:
        log.info('purge summaries=%s jobs=%s', summaries, jobs)
    return summaries, jobs
