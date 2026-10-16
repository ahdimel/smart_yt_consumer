"""§11 E: the worker protocol, server side."""
import pytest

from server.config import DAY

from .conftest import USAGE, summary_md, url, vid

MIN = 60


def test_claim_empty_queue(env):                                                 # E1
    r = env.claim()
    assert r.status_code == 204
    w = env.sql('SELECT last_seen, version FROM worker')[0]
    assert w['last_seen'] == env.clock() and w['version'] == 'test'


def test_claim_payload(env):
    u = env.user()
    env.submit(u, f'Look https://youtu.be/{vid(1)}?si=x')
    job = env.claimed()
    assert job['url'] == f'https://www.youtube.com/watch?v={vid(1)}'
    assert job['video_id'] == vid(1) and job['attempt'] == 1 and job['max_minutes'] == 180
    assert job['lease_until'] == env.clock() + env.settings.lease_seconds


def test_claim_is_fifo_and_respects_not_before(env):                             # E2
    u = env.user()
    for n in (1, 2, 3):
        env.submit(u, url(n))
        env.clock.advance(1)
    env.fail(env.claimed(), 'fetch_failed')                 # vid 1 backs off 5 min
    assert env.claimed()['video_id'] == vid(2)
    assert env.claimed()['video_id'] == vid(3)
    assert env.claim().status_code == 204
    env.clock.advance(5 * MIN)
    assert env.claimed()['video_id'] == vid(1)


def test_expired_lease_is_re_leased(env):                                        # E3
    u = env.user()
    env.submit(u, url(1))
    first = env.claimed()
    assert env.claim().status_code == 204                   # still leased
    env.clock.advance(env.settings.lease_seconds + 1)
    second = env.claimed()
    assert second['job_id'] == first['job_id'] and second['lease_id'] != first['lease_id']
    assert second['attempt'] == 2 and env.job(first['job_id'])['attempts'] == 2
    assert env.complete(first).status_code == 409           # the stale worker can't report
    assert env.complete(second).status_code == 200


def test_complete_twice_is_a_no_op(env):                                         # E4
    u = env.user()
    env.submit(u, url(1))
    lease = env.claimed()
    assert env.complete(lease).status_code == 200
    assert env.complete(lease).status_code == 200
    assert len(env.mailer.sent) == 1
    assert env.job(lease['job_id'])['input_tokens'] == USAGE['input_tokens']


def test_complete_after_failure_or_re_lease_conflicts(env):                      # E5
    u = env.user()
    env.submit(u, url(1))
    lease = env.claimed()
    env.fail(lease, 'unavailable')
    sent = len(env.mailer.sent)
    assert env.complete(lease).status_code == 409
    job = env.job(lease['job_id'])
    assert job['status'] == 'failed' and job['input_tokens'] == 0
    assert len(env.mailer.sent) == sent
    assert env.sql('SELECT COUNT(*) FROM summaries')[0][0] == 0

    env.submit(u, url(2))
    lease = env.claimed()
    env.fail(lease, 'fetch_failed')                          # requeued; old lease is dead
    assert env.complete(lease).status_code == 409
    assert env.job(lease['job_id'])['status'] == 'queued'


def test_complete_with_bad_front_matter(env):                                    # E6
    u = env.user()
    env.submit(u, url(1))
    lease = env.claimed()
    for md in ('just prose', '```markdown\n' + summary_md() + '```', '---\nnav: x\n---\nbody',
               '---\ntitle: never closed\n', '', None, 42):
        r = env.client.post(f'/worker/jobs/{lease["job_id"]}/complete', headers=env.W,
                            json={'lease_id': lease['lease_id'], 'md': md, 'usage': USAGE})
        assert r.status_code == 422, md
    job = env.job(lease['job_id'])
    assert job['status'] == 'running' and job['lease_id'] == lease['lease_id']
    assert job['input_tokens'] == 0 and env.mailer.sent == []
    assert env.fail(lease, 'invalid_output', usage=USAGE).status_code == 200
    assert env.job(lease['job_id'])['input_tokens'] == USAGE['input_tokens']


def test_complete_body_limit(env):                                               # E7
    u = env.user()
    env.submit(u, url(1))
    lease = env.claimed()
    r = env.complete(lease, md=summary_md(body='x' * (1024 * 1024)))
    assert r.status_code == 413
    assert env.job(lease['job_id'])['status'] == 'running'


def test_retryable_failure_backs_off_then_fails(env):                            # E8
    u = env.user()
    env.submit(u, url(1))
    for delay in (5 * MIN, 15 * MIN):
        lease = env.claimed()
        assert env.fail(lease, 'fetch_failed').status_code == 200
        job = env.job(lease['job_id'])
        assert job['status'] == 'queued' and job['not_before'] == env.clock() + delay
        assert job['lease_id'] is None and env.mailer.sent == []
        env.clock.advance(delay)
    lease = env.claimed()
    assert lease['attempt'] == 3
    env.fail(lease, 'fetch_failed')
    job = env.job(lease['job_id'])
    assert job['status'] == 'failed' and job['error_code'] == 'fetch_failed'
    assert job['finished_at'] == env.clock() and len(env.mailer.sent) == 1


def test_summarize_failed_retries_once(env):                                     # E8, §5.5
    u = env.user()
    env.submit(u, url(1))
    env.fail(env.claimed(), 'summarize_failed')
    env.clock.advance(5 * MIN)
    lease = env.claimed()
    env.fail(lease, 'summarize_failed')
    assert env.job(lease['job_id'])['status'] == 'failed'


@pytest.mark.parametrize('code', ['no_captions', 'too_long', 'unavailable', 'live_or_upcoming',
                                  'members_only', 'age_restricted'])
def test_permanent_failure(env, code):                                           # E9
    u = env.user()
    r = env.submit(u, url(1))
    lease = env.claimed()
    assert env.fail(lease, code).status_code == 200
    job = env.job(lease['job_id'])
    assert job['status'] == 'failed' and job['error_code'] == code and job['attempts'] == 1
    assert len(env.mailer.sent) == 1 and env.mailer.sent[0]['to'] == u.email
    status = env.submit(u, url(1))                       # a new request, not the failed one
    assert status.json()['id'] != r.json()['id']
    for n in range(2, 6):                                # 5 slots: the failure used none
        assert env.submit(u, url(n)).status_code == 202


def test_fail_replay_and_unknown_code(env):
    u = env.user()
    env.submit(u, url(1))
    lease = env.claimed()
    assert env.fail(lease, 'no_such_code').status_code == 422
    assert env.fail(lease, 'unavailable').status_code == 200
    assert env.fail(lease, 'unavailable').status_code == 200
    assert len(env.mailer.sent) == 1
    assert env.client.post('/worker/jobs/999/fail', headers=env.W,
                           json={'lease_id': 'x', 'error_code': 'unavailable'}).status_code == 404


def test_usage_accumulates_across_attempts(env):                                 # E10
    u = env.user()
    env.submit(u, url(1))
    lease = env.claimed()
    env.fail(lease, 'summarize_failed', usage=USAGE, cost=0.25)
    env.clock.advance(5 * MIN)
    lease = env.claimed()
    env.complete(lease, usage=USAGE, cost=0.5)
    job = env.job(lease['job_id'])
    assert job['input_tokens'] == 2 * USAGE['input_tokens']
    assert job['cache_write_tokens'] == 2 * USAGE['cache_creation_input_tokens']
    assert job['cache_read_tokens'] == 2 * USAGE['cache_read_input_tokens']
    assert job['output_tokens'] == 2 * USAGE['output_tokens']
    assert job['cost_usd'] == pytest.approx(0.75)
    assert job['model'] == 'claude-opus-5'


def test_garbage_usage_is_ignored_not_trusted(env):
    u = env.user()
    env.submit(u, url(1))
    lease = env.claimed()
    env.complete(lease, usage={'input_tokens': -5, 'output_tokens': 'lots',
                               'cache_read_input_tokens': True}, cost=-1)
    job = env.job(lease['job_id'])
    assert (job['input_tokens'], job['output_tokens'], job['cache_read_tokens'],
            job['cost_usd']) == (0, 0, 0, 0)


def test_pause_mid_job(env):                                                     # E11
    u = env.user()
    env.submit(u, url(1))
    env.submit(u, url(2))
    lease = env.claimed()
    env.set(paused=1)
    assert env.complete(lease).status_code == 200
    assert env.job(lease['job_id'])['status'] == 'done'
    assert env.claim().status_code == 204


def test_summary_is_stored_with_retention(env):
    u = env.user()
    env.submit(u, url(1))
    env.summarize(md=summary_md(title='"Quoted title"', verdict='**Watch.** Yes.'))
    s = env.sql('SELECT * FROM summaries')[0]
    assert s['title'] == 'Quoted title' and s['verdict'] == '**Watch.** Yes.'
    assert s['expires_at'] == env.clock() + 30 * DAY
