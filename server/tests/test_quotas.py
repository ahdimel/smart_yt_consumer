"""§11 C: quotas, global caps, the token ceiling and pause."""
import threading

from server.config import DAY

from .conftest import USAGE_TOTAL, url, vid


def submit_n(env, user, start, n, step=60):
    for i in range(start, start + n):
        r = env.submit(user, url(i))
        assert r.status_code == 202, (i, r.text)
        env.clock.advance(step)


def seed_summary(env, n, age=0):
    with env.db() as conn:
        conn.execute('INSERT INTO summaries (video_id, md, title, created_at, expires_at) '
                     'VALUES (?, ?, ?, ?, ?)',
                     (vid(n), '---\ntitle: t\n---\n', 't', env.clock() - age,
                      env.clock() - age + 30 * DAY))


def test_daily_limit(env):                                                       # C1
    u = env.user()
    t1 = env.clock()
    submit_n(env, u, 1, 5)
    r = env.submit(u, url(6))
    assert r.status_code == 429
    assert r.json()['error'] == 'quota_daily'
    assert r.json()['retry_at'] == t1 + DAY


def test_window_rolls(env):                                                      # C2
    u = env.user()
    t1 = env.clock()
    submit_n(env, u, 1, 5, step=0)
    env.clock.now = t1 + DAY + 1
    assert env.submit(u, url(6)).status_code == 202


def test_weekly_limit(env):                                                      # C3
    u = env.user()
    for day in range(4):
        submit_n(env, u, day * 10, 5, step=0)
        env.clock.advance(DAY + 1)
    r = env.submit(u, url(99))
    assert r.status_code == 429 and r.json()['error'] == 'quota_weekly'


def test_failures_dont_count(env):                                               # C4
    u = env.user()
    submit_n(env, u, 1, 5)
    for _ in range(5):
        assert env.fail(env.claimed(), 'no_captions').status_code == 200
    assert env.submit(u, url(6)).status_code == 202


def test_cache_hits_dont_count(env):                                             # C5
    u = env.user()
    for n in range(10):
        seed_summary(env, n)
    for n in range(10):
        r = env.submit(u, url(n))
        assert r.status_code == 200 and r.json()['status'] == 'done'
    assert env.submit(u, url(50)).status_code == 202


def test_queued_and_running_count(env):                                          # C6
    u = env.user()
    submit_n(env, u, 1, 5)
    env.claimed(), env.claimed()
    assert env.sql("SELECT COUNT(*) FROM jobs WHERE status = 'running'")[0][0] == 2
    assert env.submit(u, url(6)).status_code == 429


def test_per_user_override(env):                                                 # C7
    u = env.user(daily_limit=10)
    submit_n(env, u, 1, 10)
    assert env.submit(u, url(11)).status_code == 429


def test_global_cap(env):                                                        # C8
    friends = [env.user() for _ in range(9)]
    for i, f in enumerate(friends[:8]):
        submit_n(env, f, i * 10, 5, step=1)
    r = env.submit(friends[8], url(100))
    assert r.status_code == 429 and r.json()['error'] == 'busy'
    seed_summary(env, 200)
    assert env.submit(friends[8], url(200)).json()['status'] == 'done'


def test_token_ceiling_stops_claims_not_submissions(env):                        # C9
    env.set(global_daily_token_ceiling=USAGE_TOTAL)
    u = env.user()
    submit_n(env, u, 1, 2)
    env.summarize()
    assert env.submit(u, url(3)).status_code == 202
    assert env.claim().status_code == 204
    env.clock.advance(DAY + 1)
    assert env.claim().status_code == 200


def test_pause(env):                                                             # C10
    u = env.user()
    submit_n(env, u, 1, 2)
    env.set(paused=1)
    r = env.submit(u, url(3))
    assert r.status_code == 503 and r.json()['error'] == 'paused' and r.json()['message']
    assert env.claim().status_code == 204
    env.set(paused=0)
    assert env.claimed()['video_id'] == vid(1)
    assert env.claimed()['video_id'] == vid(2)


def test_concurrent_submissions_cannot_overspend(env):                           # C11
    u = env.user()
    submit_n(env, u, 1, 3)
    results = []

    def go(n):
        results.append(env.submit(u, url(100 + n)).status_code)

    threads = [threading.Thread(target=go, args=(n,)) for n in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [202, 202] + [429] * 8
    assert env.sql('SELECT COUNT(*) FROM jobs')[0][0] == 5


def test_same_video_in_flight_returns_existing_job(env):                         # C12
    u = env.user()
    first = env.submit(u, url(1))
    again = env.submit(u, f'https://www.youtube.com/watch?v={vid(1)}&t=30')
    assert again.status_code == 200 and again.json()['id'] == first.json()['id']
    env.claimed()
    assert env.submit(u, url(1)).json()['id'] == first.json()['id']        # running too
    assert env.sql('SELECT COUNT(*) FROM jobs')[0][0] == 1
    submit_n(env, u, 2, 4)                                                  # 5 slots, 1 used


def test_max_minutes_reaches_worker(env):                                        # C13
    u = env.user(max_minutes=45)
    env.submit(u, url(1))
    assert env.claimed()['max_minutes'] == 45
