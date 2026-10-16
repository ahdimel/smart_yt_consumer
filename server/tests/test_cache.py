"""§11 D: the shared summary cache and coalescing of identical in-flight requests."""
from server.config import DAY, RETENTION

from .conftest import USAGE, summary_md, url, vid

TOKENS = ('input_tokens', 'cache_write_tokens', 'cache_read_tokens', 'output_tokens')


def test_cache_hit_is_instant_and_free(env):                                     # D1
    a, b = env.user(), env.user()
    env.submit(a, url(1))
    env.summarize()
    env.clock.advance(10 * DAY)
    r = env.submit(b, url(1))
    assert r.status_code == 200 and r.json()['status'] == 'done'
    job = env.job_by_public(r.json()['id'])
    assert job['cache_hit'] == 1 and job['user_id'] == b.id
    assert all(job[k] == 0 for k in TOKENS) and job['cost_usd'] == 0
    assert job['email_status'] == 'sent'
    assert [m['to'] for m in env.mailer.sent] == [a.email, b.email]
    assert env.claim().status_code == 204


def test_expired_cache_queues_fresh_job(env):                                    # D2
    a, b = env.user(), env.user()
    env.submit(a, url(1))
    env.summarize()
    env.clock.advance(RETENTION + 1)
    r = env.submit(b, url(1))
    assert r.status_code == 202 and r.json()['status'] == 'queued'
    assert env.job_by_public(r.json()['id'])['cache_hit'] == 0


def test_cache_hit_reveals_nothing_about_first_requester(env):                   # D3
    a, b = env.user(), env.user()
    admin = env.user(admin=True)
    ra = env.submit(a, url(1))
    env.summarize()
    env.clock.advance(3600)
    rb = env.submit(b, url(1))
    assert set(rb.json()) == {'id', 'status', 'created_at', 'summary_url'}
    assert ra.json()['id'] not in rb.text
    assert rb.json()['id'] != ra.json()['id']
    for leak in (a.email, 'Friend 1', str(env.job_by_public(ra.json()['id'])['created_at'])):
        assert leak not in rb.text
    row = [r for r in env.client.get('/admin/usage.json', headers=admin.cookie).json()['requests']
           if r['user_id'] == b.id][0]
    assert row['cache_hit'] is True and sum(row['tokens'].values()) == 0


def test_coalescing(env):                                                        # D4
    a, b = env.user(), env.user()
    ra = env.submit(a, url(1))
    rb = env.submit(b, url(1))
    assert rb.status_code == 202
    ja, jb = env.job_by_public(ra.json()['id']), env.job_by_public(rb.json()['id'])
    assert jb['coalesced_with'] == ja['id']

    lease = env.claimed()
    assert lease['job_id'] == ja['id']
    assert env.claim().status_code == 204                   # one summarization, not two
    assert env.complete(lease).status_code == 200

    ja, jb = env.job(ja['id']), env.job(jb['id'])
    assert ja['status'] == jb['status'] == 'done'
    assert sorted(m['to'] for m in env.mailer.sent) == sorted([a.email, b.email])
    assert ja['input_tokens'] == USAGE['input_tokens'] and ja['cost_usd'] == 0.5
    assert all(jb[k] == 0 for k in TOKENS) and jb['cost_usd'] == 0
    # b's ride-along cost b no quota
    for n in range(2, 7):
        assert env.submit(b, url(n)).status_code == 202


def test_coalesced_jobs_fail_together(env):                                      # D5
    a, b = env.user(), env.user()
    ja = env.job_by_public(env.submit(a, url(1)).json()['id'])
    jb = env.job_by_public(env.submit(b, url(1)).json()['id'])
    assert env.fail(env.claimed(), 'no_captions').status_code == 200
    ja, jb = env.job(ja['id']), env.job(jb['id'])
    assert ja['status'] == jb['status'] == 'failed'
    assert ja['error_code'] == jb['error_code'] == 'no_captions'
    assert sorted(m['to'] for m in env.mailer.sent) == sorted([a.email, b.email])


def test_coalesced_job_waits_through_retries(env):                               # D5
    a, b = env.user(), env.user()
    ja = env.job_by_public(env.submit(a, url(1)).json()['id'])
    jb = env.job_by_public(env.submit(b, url(1)).json()['id'])
    for _ in range(2):
        env.fail(env.claimed(), 'fetch_failed')
        assert env.job(jb['id'])['status'] == 'queued' and env.mailer.sent == []
        env.clock.advance(3600)
    env.fail(env.claimed(), 'fetch_failed')
    assert env.job(ja['id'])['status'] == env.job(jb['id'])['status'] == 'failed'
    assert len(env.mailer.sent) == 2


def test_late_request_coalesces_onto_running_job(env):                           # D4
    a, b = env.user(), env.user()
    env.submit(a, url(1))
    lease = env.claimed()
    jb = env.job_by_public(env.submit(b, url(1)).json()['id'])
    assert jb['coalesced_with'] == lease['job_id']
    env.complete(lease)
    assert env.job(jb['id'])['status'] == 'done'


def test_failures_are_never_cached(env):                                         # D6
    a, b = env.user(), env.user()
    env.submit(a, url(1))
    lease = env.claimed()
    assert env.complete(lease, md='no front matter here').status_code == 422
    assert env.complete(lease, md=summary_md(title='')).status_code == 422
    env.fail(lease, 'invalid_output')
    env.clock.advance(3600)
    env.fail(env.claimed(), 'summarize_failed')
    assert env.job(lease['job_id'])['status'] == 'failed'
    assert env.sql('SELECT COUNT(*) FROM summaries')[0][0] == 0
    r = env.submit(b, url(1))
    assert r.status_code == 202 and env.job_by_public(r.json()['id'])['cache_hit'] == 0
    assert vid(1) == env.claimed()['video_id']
