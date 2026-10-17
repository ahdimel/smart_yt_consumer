"""§11 K1–K2: the retention purge. Content goes after 30 days; usage stays."""
import threading
import time
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from server import cli, db, mail, retention
from server.app import create_app
from server.config import RETENTION

from .conftest import CANARY, Env, summary_md, url, vid

# Every jobs column except video_id: the purge must leave all of them as they were (K1).
KEPT = ('id, public_id, user_id, status, cache_hit, coalesced_with, attempts, not_before, '
        'lease_until, lease_id, error_code, input_tokens, cache_write_tokens, cache_read_tokens, '
        'output_tokens, cost_usd, model, usage_at, email_status, email_attempts, created_at, '
        'finished_at')


def purge(env):
    with env.db() as conn:
        return retention.purge(conn, env.clock())


def seed(env):
    """At T0: a done job, a cache hit on it, a final failure, a running job and a queued one."""
    a, b = env.user(), env.user()
    done = env.submit(a, url(1)).json()['id']
    env.summarize(summary_md(title=f'{CANARY} title', body=f'{CANARY}-body ' * 400))
    hit = env.submit(b, url(1)).json()['id']
    env.submit(a, url(2))
    env.fail(env.claimed(), 'no_captions')
    env.submit(a, url(3))
    env.claimed()                                                   # url(3) is now running
    env.submit(b, url(4))                                           # url(4) waits, queued
    return a, b, done, hit


def jobs(env):
    return {r['id']: dict(r) for r in env.sql(f'SELECT {KEPT} FROM jobs')}


def video_ids(env):
    return {r['status']: r['video_id'] for r in env.sql('SELECT status, video_id, cache_hit FROM jobs')
            if r['cache_hit'] == 0} | {
        'hit': env.sql('SELECT video_id FROM jobs WHERE cache_hit = 1')[0]['video_id']}


def test_purge_at_day_30_plus_1s(env):                                           # K1
    admin = env.user(admin=True)
    _, _, done, hit = seed(env)
    env.clock.advance(RETENTION + 1)
    before = jobs(env)
    usage = env.client.get('/admin/usage.json', headers=admin.cookie).json()

    assert purge(env) == (1, 3)                       # done, cache hit, failed; not running, queued
    assert env.sql('SELECT * FROM summaries') == []
    assert video_ids(env) == {'done': None, 'hit': None, 'failed': None,
                              'running': vid(3), 'queued': vid(4)}
    assert jobs(env) == before                                      # usage columns intact
    assert env.client.get('/admin/usage.json', headers=admin.cookie).json() == usage
    for public_id in (done, hit):
        assert env.client.get(f'/s/{public_id}').status_code == 410


def test_nothing_goes_a_second_early(env):
    _, _, done, _ = seed(env)
    env.clock.advance(RETENTION - 1)
    assert purge(env) == (0, 0)
    assert env.client.get(f'/s/{done}').status_code == 200
    env.clock.advance(1)                              # the second the link stops working
    assert env.client.get(f'/s/{done}').status_code == 410
    assert purge(env) == (1, 3)


def test_old_queued_job_keeps_its_video(env):
    """The Mac was off for over 30 days: the job still has to be fetchable when it wakes."""
    u = env.user()
    env.submit(u, url(1))
    env.clock.advance(RETENTION * 2)
    assert purge(env) == (0, 0)
    lease = env.claimed()
    assert lease['video_id'] == vid(1)
    env.complete(lease)
    assert env.sql('SELECT video_id FROM summaries')[0][0] == vid(1)


def test_link_life_follows_the_job_not_the_cache(env):
    """A cache refreshed by a later request keeps the summary; the old job's link still goes."""
    a, b = env.user(), env.user()
    old = env.submit(a, url(1)).json()['id']
    env.summarize()
    env.clock.advance(RETENTION + 1)
    env.submit(b, url(1))                             # cache expired: redone
    env.summarize()
    assert purge(env) == (0, 1)
    assert env.job_by_public(old)['video_id'] is None
    assert [r['video_id'] for r in env.sql('SELECT video_id FROM summaries')] == [vid(1)]


def test_purge_is_idempotent(env):                                               # K2
    seed(env)
    env.clock.advance(RETENTION + 1)
    assert purge(env) == (1, 3)
    after = (jobs(env), video_ids(env))
    assert purge(env) == (0, 0)
    assert (jobs(env), video_ids(env)) == after


def test_purge_concurrent_with_submits(env):                                     # K2
    """Purges on their own connection while friends submit: no lock errors, no lost jobs, and
    every submit sees the expired summary as gone and the live one as a hit."""
    first = env.user()
    env.submit(first, url(1))
    env.summarize()                                   # vid(1) cached at T0
    env.clock.advance(RETENTION - 10)
    env.submit(first, url(2))
    env.summarize()                                   # vid(2) cached at T0 + 30d - 10s
    env.clock.advance(20)                             # vid(1) expired, vid(2) live

    errors, passes = [], []
    stop = threading.Event()

    def purger():
        with env.db() as conn:
            while not stop.is_set():
                try:
                    passes.append(retention.purge(conn, env.clock()))
                except Exception as e:                # noqa: BLE001 - the assertion reports it
                    errors.append(e)

    t = threading.Thread(target=purger)
    t.start()
    try:
        friends = [env.user() for _ in range(12)]
        replies = [env.submit(f, url(1 if i % 2 else 2)) for i, f in enumerate(friends)]
    finally:
        stop.set()
        t.join()

    assert errors == [] and len(passes) > 1
    assert all(r.status_code in (200, 202) for r in replies), [r.text for r in replies]
    rows = env.sql('SELECT video_id, status, cache_hit, coalesced_with FROM jobs WHERE id > 2')
    assert len(rows) == 12
    redo = [r for r in rows if r['video_id'] == vid(1)]
    hits = [r for r in rows if r['video_id'] == vid(2)]
    assert len(redo) == 6 and all(r['status'] == 'queued' for r in redo)
    assert sum(r['coalesced_with'] is None for r in redo) == 1      # one primary, five riders
    assert len(hits) == 6 and all(r['cache_hit'] == 1 for r in hits)
    assert [r[0] for r in env.sql('SELECT video_id FROM summaries')] == [vid(2)]


def test_purged_content_is_not_left_on_disk(env):
    """secure_delete zeroes the freed pages and the WAL is truncated: the bytes are gone."""
    seed(env)
    path = Path(env.settings.db_path)

    def on_disk():
        return b''.join(p.read_bytes() for p in (path, Path(f'{path}-wal')) if p.exists())

    assert CANARY.encode() in on_disk()
    env.clock.advance(RETENTION + 1)
    purge(env)
    data = on_disk()
    for gone in (CANARY, vid(1), vid(2)):
        assert gone.encode() not in data, gone
    assert vid(3).encode() in data and vid(4).encode() in data      # still in flight


def test_app_purges_at_start_without_a_mailer(tmp_path):
    env = Env(tmp_path / 'loop.db')
    seed(env)
    env.clock.advance(RETENTION + 1)
    app = create_app(env.settings, env.clock, None)
    assert app.state.mailer is None
    with TestClient(app):
        deadline = time.time() + 5
        while env.sql('SELECT * FROM summaries') and time.time() < deadline:
            time.sleep(0.02)
    assert env.sql('SELECT * FROM summaries') == []


def test_no_email_for_a_summary_already_gone(env, caplog):
    """An email still retrying when its summary goes isn't sent, and isn't a failure email."""
    u = env.user()
    env.mailer.outcome = 'retry'
    env.submit(u, url(1))
    lease = env.summarize()
    assert env.job(lease['job_id'])['email_status'] == 'pending'
    sent = len(env.mailer.sent)
    env.clock.advance(RETENTION + 1)
    purge(env)
    env.mailer.outcome = 'sent'
    with env.db() as conn:
        mail.deliver_pending(conn, env.mailer, 'https://testserver', env.clock())
    assert len(env.mailer.sent) == sent
    assert env.job(lease['job_id'])['email_status'] == 'failed'
    assert f'mail job={lease["job_id"]} attempt=2 outcome=expired' in caplog.text


def test_purge_logs_counts_only(env, caplog):
    caplog.set_level('INFO', logger='server')
    seed(env)
    env.clock.advance(RETENTION + 1)
    purge(env)
    lines = [r.getMessage() for r in caplog.records if r.name == 'server']
    assert 'purge summaries=1 jobs=3' in lines
    assert not any(CANARY in line or 'v0' in line for line in lines)


def test_cli_purge(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'cli.db'
    db.init(str(path))
    with closing(db.connect(str(path))) as conn:
        conn.execute("INSERT INTO summaries VALUES ('v0000000001', 'md', 't', NULL, 0, 1)")
    monkeypatch.setenv('DB_PATH', str(path))
    assert cli.main(['purge']) is None
    assert capsys.readouterr().out.strip() == 'purged summaries=1 jobs=0'


def test_cli_vacuum_drops_content_freed_before_secure_delete(tmp_path, monkeypatch, capsys):
    """A database from before M5 can hold overwritten summaries in its free pages."""
    import sqlite3
    path = tmp_path / 'old.db'
    db.init(str(path))
    raw = sqlite3.connect(str(path), isolation_level=None)          # no secure_delete: pre-M5
    raw.execute("INSERT INTO summaries VALUES ('v0000000001', ?, 't', NULL, 0, 9999999999)",
                (f'{CANARY} ' * 2000,))
    raw.execute("UPDATE summaries SET md = 'short'")                # a cache refresh, pre-M5
    raw.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    raw.close()
    assert CANARY.encode() in path.read_bytes()
    monkeypatch.setenv('DB_PATH', str(path))
    assert cli.main(['purge', '--vacuum']) is None
    out = capsys.readouterr().out
    assert 'purged summaries=0 jobs=0' in out and 'vacuumed free_pages=' in out
    assert CANARY.encode() not in path.read_bytes()
    assert env_rows(path) == [('v0000000001', 'short')]


def env_rows(path):
    with closing(db.connect(str(path))) as conn:
        return [tuple(r) for r in conn.execute('SELECT video_id, md FROM summaries')]
