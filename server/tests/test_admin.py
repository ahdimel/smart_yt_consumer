"""§11 G: the admin view shows usage and never content."""
import re

from server.config import DAY

from .conftest import CANARY, ORIGIN, summary_md, url, vid

TOKENS = ('input_tokens', 'cache_write_tokens', 'cache_read_tokens', 'output_tokens')


def post(env, admin, path, data=None):
    return env.client.post(path, data=data or {}, headers={**admin.cookie, 'Origin': ORIGIN},
                           follow_redirects=False)


def seed_job(env, user, age, status='done', tokens=(0, 0, 0, 0), cost=0.0, cache_hit=0,
             error_code=None):
    with env.db() as conn:
        conn.execute(
            'INSERT INTO jobs (public_id, user_id, video_id, status, cache_hit, error_code, '
            'input_tokens, cache_write_tokens, cache_read_tokens, output_tokens, cost_usd, '
            'created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (f'p{age}-{user.id}-{status}', user.id, vid(age), status, cache_hit, error_code,
             *tokens, cost, env.clock() - age))


def test_per_user_windows(env):                                                  # G1
    admin, a, b = env.user(admin=True), env.user(), env.user()
    seed_job(env, a, 3600, tokens=(10, 1, 2, 5), cost=0.1)              # 24h
    seed_job(env, a, 2 * DAY, tokens=(20, 0, 0, 10), cost=0.2)          # 7d
    seed_job(env, a, 30 * DAY, tokens=(40, 0, 0, 20), cost=0.4)         # all
    seed_job(env, a, 60, status='failed', error_code='no_captions')
    seed_job(env, a, 120, cache_hit=1)
    seed_job(env, b, 3 * DAY, tokens=(7, 0, 0, 3))
    users = {u['id']: u for u in env.client.get('/admin/usage.json', headers=admin.cookie).json()['users']}
    wa = users[a.id]['windows']
    assert [wa[w]['requests'] for w in ('24h', '7d', 'all')] == [3, 4, 5]
    assert wa['24h']['tokens'] == dict(zip(TOKENS, (10, 1, 2, 5)))
    assert wa['7d']['tokens']['input_tokens'] == 30
    assert wa['all']['tokens']['output_tokens'] == 35
    assert wa['all']['cost_usd_api_equivalent'] == 0.7
    assert wa['all']['cache_hits'] == 1 and wa['all']['failed'] == 1
    assert users[a.id]['failures_by_code'] == {'no_captions': 1}
    wb = users[b.id]['windows']
    assert [wb[w]['requests'] for w in ('24h', '7d', 'all')] == [0, 1, 1]


def test_token_columns_and_cost_label(env):                                      # G2
    admin = env.user(admin=True)
    page = env.client.get('/admin', headers=admin.cookie).text
    assert 'API-equivalent' in page
    for col in ('in', 'cache-write', 'cache-read', 'out'):
        assert col in page
    data = env.client.get('/admin/usage.json', headers=admin.cookie).json()
    assert set(data['users'][0]['windows']['all']['tokens']) == set(TOKENS)
    assert 'cost_usd_api_equivalent' in data['users'][0]['windows']['all']


def test_no_content_in_any_admin_response(env):                                  # G3
    admin, a, b = env.user(admin=True), env.user(), env.user()
    publics = []
    for n, who in ((1, a), (2, b), (3, a)):
        publics.append(env.submit(who, url(n)).json()['id'])
    env.summarize(md=summary_md(title=f'{CANARY} title', verdict=f'{CANARY}-verdict',
                                body=f'{CANARY}-body'))
    env.fail(env.claimed(), 'no_captions')
    lease = env.claimed()
    env.client.post(f'/worker/jobs/{lease["job_id"]}/complete', headers=env.W,
                    json={'lease_id': lease['lease_id'], 'md': f'{CANARY} broken'})
    publics.append(env.submit(b, url(1)).json()['id'])                  # cache hit

    responses = [
        env.client.get('/admin', headers=admin.cookie),
        env.client.get('/admin/usage.json', headers=admin.cookie),
        post(env, admin, '/admin/pause'),
        post(env, admin, '/admin/resume'),
        post(env, admin, '/admin/settings', {'global_daily_limit': '40',
                                              'global_daily_token_ceiling': ''}),
        post(env, admin, f'/admin/users/{a.id}/limits',
             {'daily_limit': '5', 'weekly_limit': '20', 'max_minutes': '180'}),
        post(env, admin, '/admin/invites', {'name': 'New', 'email': 'new@example.org'}),
        post(env, admin, f'/admin/users/{b.id}/reissue'),
        post(env, admin, f'/admin/users/{a.id}/revoke'),
        env.client.get('/admin', headers=admin.cookie),
    ]
    forbidden = [CANARY, 'youtube', 'youtu.be', *(vid(n) for n in (1, 2, 3)), *publics]
    for r in responses:
        assert r.status_code in (200, 303)
        for word in forbidden:
            assert word not in r.text, (r.request.url, word)
            assert word not in str(r.headers), (r.request.url, word)


def test_invite_revoke_limits_reissue(env):                                      # G4
    admin = env.user(admin=True)
    r = post(env, admin, '/admin/invites', {'name': 'Sam', 'email': 'sam@example.org'})
    token = re.search(r'/u/([A-Za-z0-9_-]+)', r.text).group(1)
    assert env.client.get(f'/u/{token}', follow_redirects=False).status_code == 303
    uid = env.sql('SELECT id FROM users WHERE name = ?', 'Sam')[0][0]
    sam = {'Authorization': f'Bearer {token}'}

    assert post(env, admin, f'/admin/users/{uid}/limits',
                {'daily_limit': '7', 'weekly_limit': '20', 'max_minutes': '60'}).status_code == 303
    for n in range(7):
        assert env.client.post('/api/requests', json={'url': url(n)}, headers=sam).status_code == 202
    assert env.client.post('/api/requests', json={'url': url(8)}, headers=sam).status_code == 429
    assert env.claimed()['max_minutes'] == 60

    assert post(env, admin, f'/admin/users/{uid}/revoke').status_code == 303
    assert env.client.post('/api/requests', json={'url': url(9)}, headers=sam).status_code == 401

    r = post(env, admin, f'/admin/users/{uid}/reissue')
    fresh = re.search(r'/u/([A-Za-z0-9_-]+)', r.text).group(1)
    assert fresh != token
    assert env.client.get(f'/u/{token}', follow_redirects=False).status_code == 404
    assert env.client.get(f'/u/{fresh}', follow_redirects=False).status_code == 303


def test_admin_input_validation(env):
    admin = env.user(admin=True)
    assert post(env, admin, f'/admin/users/{admin.id}/revoke').status_code == 400
    assert post(env, admin, f'/admin/users/{admin.id}/limits',
                {'daily_limit': '-1', 'weekly_limit': '1', 'max_minutes': '1'}).status_code == 400
    assert post(env, admin, '/admin/invites', {'name': '', 'email': 'x'}).status_code == 400
    assert post(env, admin, '/admin/users/999/reissue').status_code == 404
    r = env.client.post('/admin/pause', headers={**admin.cookie, 'Origin': 'https://evil.example'})
    assert r.status_code == 403 and env.sql('SELECT paused FROM settings')[0][0] == 0


def test_pause_button(env):                                                      # G5
    admin, u = env.user(admin=True), env.user()
    env.submit(u, url(1))
    assert 'Pause everything' in env.client.get('/admin', headers=admin.cookie).text
    assert post(env, admin, '/admin/pause').status_code == 303
    assert 'Resume' in env.client.get('/admin', headers=admin.cookie).text
    assert env.submit(u, url(2)).status_code == 503
    assert env.claim().status_code == 204
    post(env, admin, '/admin/resume')
    assert env.claimed()['video_id'] == vid(1)
    assert env.submit(u, url(2)).status_code == 202


def test_settings_form(env):
    admin = env.user(admin=True)
    post(env, admin, '/admin/settings', {'global_daily_limit': '12',
                                         'global_daily_token_ceiling': '500000'})
    s = env.client.get('/admin/usage.json', headers=admin.cookie).json()['settings']
    assert s['global_daily_limit'] == 12 and s['global_daily_token_ceiling'] == 500000
    post(env, admin, '/admin/settings', {'global_daily_limit': '12', 'global_daily_token_ceiling': ''})
    assert env.sql('SELECT global_daily_token_ceiling FROM settings')[0][0] is None
