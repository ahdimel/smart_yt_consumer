"""§11 B: authentication and authorization, plus M1–M4 (first visit, strangers)."""
import logging

from server import auth

from .conftest import ORIGIN, WORKER_TOKEN, url


def test_invite_sets_cookie_and_redirects(env):                                 # B1
    u = env.user()
    r = env.client.get(f'/u/{u.token}', follow_redirects=False)
    assert r.status_code == 303 and r.headers['location'] == '/'
    cookie = r.headers['set-cookie']
    for attr in ('HttpOnly', 'Secure', 'SameSite=lax', 'Path=/'):
        assert attr.lower() in cookie.lower()
    assert r.headers['referrer-policy'] == 'no-referrer'


def test_first_visit_goes_to_welcome_then_home(env):                            # M1, M2
    u = env.user(welcomed=False)
    r = env.client.get(f'/u/{u.token}', follow_redirects=False)
    assert r.headers['location'] == '/welcome'
    assert env.client.get('/welcome', headers=u.cookie).status_code == 200
    assert env.sql('SELECT welcomed_at FROM users WHERE id = ?', u.id)[0][0] == env.clock()
    r = env.client.get(f'/u/{u.token}', follow_redirects=False)
    assert r.headers['location'] == '/'


def test_unknown_token_is_plain_404(env):                                        # B2
    r = env.client.get('/u/not-a-real-token', follow_redirects=False)
    missing = env.client.get('/no/such/page')
    assert r.status_code == 404 and missing.status_code == 404
    assert r.text == missing.text
    assert 'set-cookie' not in r.headers


def test_token_misses_rate_limited_per_ip(make_env):                             # B3
    env = make_env(client_ip_header='X-Real-IP')
    u = env.user()
    a, b = {'X-Real-IP': '203.0.113.1'}, {'X-Real-IP': '203.0.113.2'}
    for i in range(10):
        assert env.client.get(f'/u/guess{i}', headers=a, follow_redirects=False).status_code == 404
    assert env.client.get('/u/guess10', headers=a, follow_redirects=False).status_code == 429
    # blocked means blocked: a valid token from that IP is refused too, so there is no oracle
    assert env.client.get(f'/u/{u.token}', headers=a, follow_redirects=False).status_code == 429
    assert env.submit(u, url(1), headers=a).status_code == 429
    assert env.client.get(f'/u/{u.token}', headers=b, follow_redirects=False).status_code == 303
    assert env.client.get('/u/guess', headers=b, follow_redirects=False).status_code == 404
    env.clock.advance(601)
    assert env.client.get(f'/u/{u.token}', headers=a, follow_redirects=False).status_code == 303


def test_bearer_misses_count_too(env):                                           # B3
    for i in range(10):
        r = env.client.post('/api/requests', json={'url': url(1)},
                            headers={'Authorization': f'Bearer guess{i}'})
        assert r.status_code == 401
    r = env.client.post('/api/requests', json={'url': url(1)},
                        headers={'Authorization': 'Bearer guess'})
    assert r.status_code == 429


def test_revocation_is_immediate(env):                                           # B4
    u = env.user()
    assert env.submit(u, url(1)).status_code == 202
    with env.db() as conn:
        conn.execute('UPDATE users SET revoked_at = ? WHERE id = ?', (env.clock(), u.id))
    assert env.submit(u, url(2)).status_code == 401
    r = env.client.post('/api/requests', json={'url': url(2)}, headers=u.cookie)
    assert r.status_code == 401
    assert 'Private, invite-only.' in env.client.get('/', headers=u.cookie).text
    assert env.client.get(f'/u/{u.token}', follow_redirects=False).status_code == 404


def test_no_credentials(env):                                                    # B5
    assert env.client.post('/api/requests', json={'url': url(1)}).status_code == 401
    assert env.client.post('/api/requests', json={'url': url(1)},
                           headers={'Authorization': 'Basic abc'}).status_code == 401


def test_bearer_and_cookie_routes(env):                                          # B6
    u = env.user()
    assert env.submit(u, url(1)).status_code == 202
    assert env.client.post('/api/requests', json={'url': url(2)},
                           headers=u.cookie).status_code == 202
    home = env.client.get('/', headers=u.cookie)
    assert home.status_code == 200 and 'Friend 1' in home.text and '<form' in home.text
    # The bearer is for the API only; it doesn't open the cookie pages.
    assert 'Private, invite-only.' in env.client.get('/', headers=u.bearer).text


def test_paste_box_form_post_redirects_home(env):                                # B6
    u = env.user()
    r = env.client.post('/api/requests', data={'url': url(1)},
                        headers={**u.cookie, 'Origin': ORIGIN}, follow_redirects=False)
    assert r.status_code == 303 and r.headers['location'] == '/?m=queued'
    assert 'Queued.' in env.client.get('/?m=queued', headers=u.cookie).text
    r = env.client.post('/api/requests', data={'url': 'nope'},
                        headers={**u.cookie, 'Origin': ORIGIN}, follow_redirects=False)
    assert r.headers['location'] == '/?m=invalid_url'


def test_admin_routes_hidden_from_non_admins(env):                               # B7
    u = env.user()
    for headers in (u.cookie, {}):
        assert env.client.get('/admin', headers=headers).status_code == 404
        assert env.client.get('/admin/usage.json', headers=headers).status_code == 404
        for path in ('/admin/pause', '/admin/invites', f'/admin/users/{u.id}/revoke'):
            assert env.client.post(path, headers={**headers, 'Origin': ORIGIN}).status_code == 404
    assert env.sql('SELECT paused FROM settings')[0][0] == 0


def test_credentials_are_not_interchangeable(env):                               # B8
    u = env.user(admin=True)
    w = {'Authorization': f'Bearer {WORKER_TOKEN}'}
    assert env.client.post('/worker/claim', headers=u.bearer).status_code == 401
    assert env.client.post('/worker/claim', headers=u.cookie).status_code == 401
    assert env.client.post('/worker/jobs/1/complete', headers=u.bearer, json={}).status_code == 401
    assert env.client.post('/api/requests', json={'url': url(1)}, headers=w).status_code == 401
    assert env.client.get('/admin', headers=w).status_code == 401
    assert env.client.get('/admin/usage.json', headers=w).status_code == 401
    assert env.client.get('/admin', headers={'Cookie': f'session={WORKER_TOKEN}'}).status_code == 404
    # an admin's own bearer doesn't open admin either: admin is cookie-only
    assert env.client.get('/admin', headers=u.bearer).status_code == 401


def test_no_worker_token_configured_means_no_worker(make_env):                   # B8
    env = make_env(worker_token=None)
    r = env.client.post('/worker/claim', headers={'Authorization': 'Bearer '})
    assert r.status_code == 401


def test_token_never_echoed(env, caplog):                                        # B9
    caplog.set_level(logging.DEBUG)
    admin = env.user(admin=True)
    u = env.user(welcomed=False)
    bodies = [
        env.client.get(f'/u/{u.token}', follow_redirects=False).text,
        env.client.get('/welcome', headers=u.cookie).text,
        env.client.get('/', headers=u.cookie).text,
        env.client.get('/about', headers=u.cookie).text,
        env.submit(u, url(1)).text,
        env.client.post('/api/requests', json={'url': url(2)}, headers=u.cookie).text,
        env.client.get('/admin', headers=admin.cookie).text,
        env.client.get('/admin/usage.json', headers=admin.cookie).text,
        env.claim().text,
    ]
    for body in bodies:
        assert u.token not in body and admin.token not in body
    # httpx's records are the test client's own request lines, not the server's
    server_side = '\n'.join(r.getMessage() for r in caplog.records if not r.name.startswith('httpx'))
    assert 'job=' in server_side
    for secret in (u.token, admin.token, WORKER_TOKEN):
        assert secret not in server_side


def test_cross_origin_post_rejected(env):                                        # B10
    u = env.user()
    for headers in ({'Origin': 'https://evil.example'},
                    {'Origin': 'null'},
                    {'Origin': 'http://testserver'},            # scheme differs
                    {'Sec-Fetch-Site': 'cross-site'},
                    {'Sec-Fetch-Site': 'same-site', 'Origin': 'https://other.testserver'}):
        r = env.client.post('/api/requests', data={'url': url(1)}, headers={**u.cookie, **headers})
        assert r.status_code == 403, headers
        assert 'access-control-allow-origin' not in r.headers
    assert env.sql('SELECT COUNT(*) FROM jobs')[0][0] == 0
    r = env.client.post('/api/requests', data={'url': url(1)},
                        headers={**u.cookie, 'Origin': ORIGIN, 'Sec-Fetch-Site': 'same-origin'},
                        follow_redirects=False)
    assert r.status_code == 303


def test_no_cors(env):                                                           # B10
    r = env.client.options('/api/requests', headers={
        'Origin': 'https://evil.example', 'Access-Control-Request-Method': 'POST'})
    assert 'access-control-allow-origin' not in r.headers
    assert r.status_code in (404, 405)


def test_invite_token_shown_once(env):                                           # B11
    admin = env.user(admin=True)
    r = env.client.post('/admin/invites', data={'name': 'Sam', 'email': 'sam@example.org'},
                        headers={**admin.cookie, 'Origin': ORIGIN})
    assert r.status_code == 200
    link = r.text.split('value="')[1].split('"')[0]
    assert link.startswith(f'{ORIGIN}/u/')
    token = link.rsplit('/', 1)[1]
    assert len(token) >= 43                                       # 256 bits, base64url
    data = env.client.get('/admin/usage.json', headers=admin.cookie)
    sam = [x for x in data.json()['users'] if x['name'] == 'Sam'][0]
    assert sam['token_prefix'] == auth.hash_token(token)[:8]
    assert token not in data.text and token not in env.client.get('/admin', headers=admin.cookie).text
    stored = env.sql('SELECT token_hash FROM users WHERE name = ?', 'Sam')[0][0]
    assert stored == auth.hash_token(token) and token not in stored
    assert env.client.get(f'/u/{token}', follow_redirects=False).status_code == 303


def test_strangers_see_one_line(env):                                            # M3, M4
    for path in ('/', '/about', '/welcome'):
        r = env.client.get(path)
        assert r.status_code == 200
        assert 'Private, invite-only.' in r.text
        assert '<form' not in r.text and '<a ' not in r.text and 'href' not in r.text
    assert env.client.get('/docs').status_code == 404
    assert env.client.get('/openapi.json').status_code == 404


def test_unknown_cookie_is_cleared(env):
    r = env.client.get('/', headers={'Cookie': 'session=stale'})
    assert 'Private, invite-only.' in r.text
    assert 'session=' in r.headers.get('set-cookie', '')


def test_security_headers_everywhere(env):
    u = env.user()
    for r in (env.client.get('/'), env.client.get('/', headers=u.cookie),
              env.client.get('/u/nope'), env.client.get('/healthz'), env.submit(u, 'bad')):
        assert "default-src 'self'" in r.headers['content-security-policy']
        assert "script-src 'self'" in r.headers['content-security-policy']
        assert "object-src 'none'" in r.headers['content-security-policy']
        assert "base-uri 'none'" in r.headers['content-security-policy']
        assert r.headers['x-robots-tag'] == 'noindex'
        assert r.headers['referrer-policy'] == 'no-referrer'
