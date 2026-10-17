"""§11 J: intake modalities. The Android share target (/share), the bookmarklet page (/add), the
manifest, the bearer API, and browser forms answering with pages rather than JSON (M4 brief).

The paste box and add.js run in a stub DOM under node (js_harness.js); the J5 test replays the
exact request add.js makes against the app and asserts on what the server saw.
"""
import glob
import json
import logging
import os
import shutil
import struct
import subprocess
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from .conftest import CANARY, ORIGIN, url, vid

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(os.path.dirname(HERE), 'static')
# What a browser sends for its own same-origin form POST under Referrer-Policy: no-referrer (M3).
BROWSER = {'Origin': 'null', 'Sec-Fetch-Site': 'same-origin'}


def node():
    found = shutil.which('node') or sorted(glob.glob(os.path.expanduser('~/.nvm/versions/node/*/bin/node')))
    return found if isinstance(found, str) else (found[-1] if found else None)


NODE = node()
needs_node = pytest.mark.skipif(NODE is None, reason='node not installed')


def run_js(name, **cfg):
    r = subprocess.run([NODE, os.path.join(HERE, 'js_harness.js'), os.path.join(STATIC, name),
                        json.dumps(cfg)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def share(env, user, data, headers=None):
    return env.client.post('/share', data=data, headers={**user.cookie, **(headers or {})},
                           follow_redirects=False)


def jobs(env):
    return env.sql('SELECT COUNT(*) FROM jobs')[0][0]


# ── /share: the Android share target ─────────────────────────────────────

def test_share_with_url_field(env):                                              # J1
    u = env.user()
    r = share(env, u, {'title': 'Some video', 'url': url(1)}, BROWSER)
    assert r.status_code == 303 and r.headers['location'] == '/?m=queued'
    assert env.sql('SELECT video_id FROM jobs')[0][0] == vid(1)


def test_share_with_link_only_in_text(env):                                     # J2
    """The YouTube app on Android leaves `url` empty and puts the link in `text`."""
    u = env.user()
    r = share(env, u, {'title': 'Some video', 'text': f'Watch this! {url(2)}', 'url': ''}, BROWSER)
    assert r.status_code == 303 and r.headers['location'] == '/?m=queued'
    assert env.sql('SELECT video_id FROM jobs')[0][0] == vid(2)


def test_share_with_only_a_title(env):                                           # J3
    u = env.user()
    r = share(env, u, {'title': 'A video someone liked'}, BROWSER)
    assert r.status_code == 303 and r.headers['location'] == '/?m=invalid_url'
    page = env.client.get(r.headers['location'], headers=u.cookie).text
    assert 'look like a single YouTube video' in page
    assert 'id="paste-form"' in page and 'name="url"' in page
    assert jobs(env) == 0


@pytest.mark.parametrize('headers', [
    {},                                                    # no origin evidence at all
    {'Sec-Fetch-Site': 'none'},                            # browser-initiated (the OS share)
    {'Sec-Fetch-Site': 'none', 'Origin': 'null'},
    {'Sec-Fetch-Site': 'same-origin', 'Origin': ORIGIN},
    BROWSER,
])
def test_share_accepts_what_a_browser_may_send(env, headers):                   # J1, §12
    u = env.user()
    assert share(env, u, {'url': url(1)}, headers).status_code == 303
    assert jobs(env) == 1


@pytest.mark.parametrize('headers', [
    {'Sec-Fetch-Site': 'cross-site'},
    {'Origin': 'https://evil.example'},
    {'Sec-Fetch-Site': 'same-site', 'Origin': 'https://other.testserver'},
])
def test_share_refuses_cross_site_with_a_page(env, headers):                    # B10
    u = env.user()
    r = share(env, u, {'url': url(1)}, headers)
    assert r.status_code == 403
    assert r.headers['content-type'].startswith('text/html')
    assert 'another site' in r.text and '"error"' not in r.text
    assert jobs(env) == 0


def test_share_is_cookie_only(env):                                              # B6
    u = env.user()
    r = env.client.post('/share', data={'url': url(1)}, headers=u.bearer, follow_redirects=False)
    assert r.status_code == 401 and 'Private, invite-only.' in r.text
    r = env.client.post('/share', data={'url': url(1)}, follow_redirects=False)
    assert r.status_code == 401 and 'Private, invite-only.' in r.text
    assert jobs(env) == 0


def test_share_logs_origin_evidence_but_no_content(env, caplog):                # §12, J5
    caplog.set_level(logging.INFO, logger='server')
    u = env.user()
    share(env, u, {'title': CANARY, 'text': f'{CANARY} {url(1)}'}, {'Sec-Fetch-Site': 'none'})
    share(env, u, {'url': url(2)}, {'Sec-Fetch-Site': 'cross-site', 'Origin': 'https://e.example'})
    lines = [r.getMessage() for r in caplog.records if r.name == 'server']
    assert 'share site=none origin=absent cookie=yes' in lines
    assert 'share site=cross-site origin=other cookie=yes' in lines
    assert 'refused cross_origin site=cross-site origin=other cookie=yes' in lines
    logged = '\n'.join(lines)
    for secret in (CANARY, vid(1), vid(2), 'youtu', 'e.example', u.token):
        assert secret not in logged


def test_provenance_never_echoes_a_header_value(env, caplog):
    caplog.set_level(logging.INFO, logger='server')
    u = env.user()
    share(env, u, {'url': url(1)}, {'Sec-Fetch-Site': CANARY, 'Origin': f'https://{CANARY}.example'})
    logged = '\n'.join(r.getMessage() for r in caplog.records if r.name == 'server')
    assert 'site=other origin=other' in logged and CANARY not in logged


# ── the manifest ─────────────────────────────────────────────────────────

def png_size(data):
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    return struct.unpack('>II', data[16:24])


def test_manifest_declares_a_post_share_target(env):                            # J4
    r = env.client.get('/manifest.webmanifest')
    assert r.status_code == 200
    assert r.headers['content-type'].startswith('application/manifest+json')
    m = r.json()
    t = m['share_target']
    assert t['action'] == '/share' and t['method'] == 'POST'
    assert t['enctype'] == 'application/x-www-form-urlencoded'
    assert t['params'] == {'title': 'title', 'text': 'text', 'url': 'url'}
    # Chrome's install criteria: a name, start_url, an app display mode, 192 and 512 icons.
    assert m['name'] and m['start_url'] == '/' and m['display'] == 'standalone'
    sizes = set()
    for icon in m['icons']:
        img = env.client.get(icon['src'])
        assert img.status_code == 200 and img.headers['content-type'] == 'image/png'
        w, h = png_size(img.content)
        assert f'{w}x{h}' == icon['sizes']
        sizes.add(icon['sizes'])
    assert {'192x192', '512x512'} <= sizes
    assert any(i['purpose'] == 'maskable' for i in m['icons'])


def test_manifest_linked_from_signed_in_pages_only(env):                        # J4, M3
    u = env.user()
    for path in ('/', '/welcome', '/about'):
        assert '<link rel="manifest" href="/manifest.webmanifest">' in \
            env.client.get(path, headers=u.cookie).text
        assert 'manifest' not in env.client.get(path).text
    apple = env.client.get('/static/apple-touch-icon.png')
    assert png_size(apple.content) == (180, 180)


# ── /add: the bookmarklet ────────────────────────────────────────────────

def recording(app, seen):
    """The ASGI app, plus a log of every request line the server receives."""
    async def wrapped(scope, receive, send):
        if scope['type'] == 'http':
            seen.append(scope['method'] + ' ' + scope['raw_path'].decode('latin-1') + '?'
                        + scope['query_string'].decode('latin-1'))
        await app(scope, receive, send)
    return wrapped


@needs_node
def test_bookmarklet_url_never_reaches_a_path_or_query(env):                    # J5
    u = env.user()
    seen = []
    client = TestClient(recording(env.app, seen), base_url=ORIGIN)
    link = f'https://www.youtube.com/watch?v={vid(5)}&t=42s'
    page = client.get(f'/add#{quote(link, safe="")}', headers=u.cookie)
    assert page.status_code == 200 and '<script src="/static/add.js" defer>' in page.text

    # What add.js does with that fragment, run for real.
    out = run_js('add.js', hash='#' + quote(link, safe=''))
    assert out['replaced'] == ['/add']                         # wiped from the address bar
    [call] = out['fetches']
    assert call['url'] == '/api/requests' and call['method'] == 'POST'
    assert call['credentials'] == 'same-origin'
    assert vid(5) not in call['url']
    assert json.loads(call['body']) == {'url': link}

    r = client.post(call['url'], content=call['body'],
                    headers={**call['headers'], **u.cookie, **BROWSER})
    assert r.status_code == 202
    assert env.sql('SELECT video_id FROM jobs')[0][0] == vid(5)
    assert out['add-status']['text'] == 'Queued. You’ll get an email when it’s ready.'

    assert seen == ['GET /add?', 'POST /api/requests?']
    for line in seen:
        assert vid(5) not in line and 'youtube' not in line


@needs_node
def test_add_script_reports_outcomes(env):
    out = run_js('add.js', hash='', opener=True)
    assert out['fetches'] == [] and 'Nothing to send' in out['add-status']['text']
    out = run_js('add.js', hash='#' + quote(url(1), safe=''),
                 response={'status': 429, 'body': {'error': 'quota_daily',
                                                   'message': "You've used all 5 of your requests today."}})
    assert out['add-status']['text'] == "You've used all 5 of your requests today."
    assert out['add-close']['hidden'] is True                # not opened by the bookmarklet
    out = run_js('add.js', hash='#' + quote(url(1), safe=''), opener=True,
                 response={'status': 200, 'body': {'status': 'done'}})
    assert out['add-status']['text'] == 'Done. The email is on its way.'
    assert out['add-close']['hidden'] is False
    out = run_js('add.js', hash='#' + quote(url(1), safe=''), response={'status': 403})
    assert 'refused' in out['add-status']['text']
    out = run_js('add.js', hash='#' + quote(url(1), safe=''), fetchFails=True)
    assert "Couldn’t reach the server" in out['add-status']['text']
    out = run_js('add.js', hash='#%E0%A4%A')                   # malformed escape: sent as typed
    assert json.loads(out['fetches'][0]['body']) == {'url': '%E0%A4%A'}


def test_add_page_needs_the_cookie(env):                                        # M4
    r = env.client.get('/add')
    assert r.status_code == 200 and 'Private, invite-only.' in r.text and 'add.js' not in r.text


def test_bookmarklet_on_desktop_setup_uses_the_fragment(env):                   # J5
    u = env.user()
    page = env.client.get('/welcome', headers=u.cookie).text
    href = page.split('class="bookmarklet" href="')[1].split('"')[0]
    assert href.startswith('javascript:')
    assert f'{ORIGIN}/add#' in href and '?' not in href
    assert 'encodeURIComponent(location.href)' in href


# ── J6: the API, by bearer ───────────────────────────────────────────────

def test_bearer_json_and_plain_text(env):                                       # J6
    u = env.user()
    r = env.client.post('/api/requests', json={'url': url(1)}, headers=u.bearer)
    assert r.status_code == 202 and r.json()['status'] == 'queued'
    r = env.client.post('/api/requests', content=f'look: {url(2)}\n',
                        headers={**u.bearer, 'Content-Type': 'text/plain'})
    assert r.status_code == 202
    r = env.client.post('/api/requests', content=url(3).encode(), headers=u.bearer)
    assert r.status_code == 202                                # no Content-Type at all
    assert jobs(env) == 3


# ── J7: no video URL in a query string, ever ─────────────────────────────

@pytest.mark.parametrize('path', ['/share', f'/share?url={url(1)}', f'/share?text={url(1)}',
                                  '/api/requests', f'/api/requests?url={url(1)}',
                                  f'/add?url={url(1)}', '/add?x'])
def test_intake_routes_refuse_get_with_a_query(env, path):                      # J7
    u = env.user()
    assert env.client.get(path, headers=u.cookie).status_code == 405
    assert jobs(env) == 0


def test_add_without_query_is_the_page(env):                                    # J7
    u = env.user()
    assert env.client.get('/add', headers=u.cookie).status_code == 200


# ── browser forms answer with pages (M4 brief) ───────────────────────────

def test_refused_paste_box_shows_a_page_not_json(make_env):
    env = make_env(client_ip_header='X-Real-IP')
    u = env.user()
    form = {**u.cookie}
    r = env.client.post('/api/requests', data={'url': url(1)},
                        headers={**form, 'Sec-Fetch-Site': 'cross-site'})
    assert r.status_code == 403 and r.headers['content-type'].startswith('text/html')
    assert 'another site' in r.text and 'Back to your page' in r.text
    r = env.client.post('/api/requests', data={'url': 'x' * 3000}, headers={**form, **BROWSER})
    assert r.status_code == 413 and 'too long' in r.text and '"error"' not in r.text
    with env.db() as conn:
        conn.execute('UPDATE users SET revoked_at = 1 WHERE id = ?', (u.id,))
    r = env.client.post('/api/requests', data={'url': url(1)}, headers={**form, **BROWSER})
    assert r.status_code == 401 and 'Private, invite-only.' in r.text
    ip = {'X-Real-IP': '203.0.113.9'}
    for i in range(10):
        env.client.get(f'/u/guess{i}', headers=ip)
    r = env.client.post('/api/requests', data={'url': url(1)},
                        headers={'Cookie': 'session=whatever', **BROWSER, **ip})
    assert r.status_code == 429 and 'Too many attempts' in r.text
    assert jobs(env) == 0


def test_quota_and_pause_redirect_with_a_message(env):
    u = env.user(daily_limit=1)
    hdr = {**u.cookie, **BROWSER}
    env.client.post('/api/requests', data={'url': url(1)}, headers=hdr)
    r = env.client.post('/api/requests', data={'url': url(2)}, headers=hdr, follow_redirects=False)
    assert r.headers['location'] == '/?m=quota_daily'
    env.set(paused=1)
    r = share(env, u, {'url': url(3)}, BROWSER)
    assert r.headers['location'] == '/?m=paused'


def test_api_clients_still_get_json(env):
    u = env.user()
    r = env.client.post('/api/requests', json={'url': 'nope'}, headers=u.cookie)
    assert r.status_code == 400 and r.json()['error'] == 'invalid_url'
    r = env.client.post('/api/requests', json={'url': url(1)},
                        headers={**u.cookie, 'Sec-Fetch-Site': 'cross-site'})
    assert r.status_code == 403 and r.json()['error'] == 'cross_origin'


# ── the paste button ─────────────────────────────────────────────────────

def test_home_has_the_paste_button(env):
    u = env.user()
    page = env.client.get('/', headers=u.cookie).text
    assert '<button type="button" id="paste" hidden>Paste and summarize</button>' in page
    assert '<script src="/static/paste.js" defer></script>' in page
    assert env.client.get('/static/paste.js').headers['content-type'].startswith('text/javascript')


@needs_node
def test_paste_button_submits_a_youtube_link(env):
    out = run_js('paste.js', clipboard=f'  {url(1)}\n', click='paste')
    assert out['paste']['hidden'] is False
    assert out['submitted'] is True and out['url']['value'] == url(1)


@needs_node
@pytest.mark.parametrize('clip', ['hunter2', 'https://vimeo.com/123', 'youtube.com.evil.com/x',
                                  'call me about youtube'])
def test_paste_button_never_sends_other_clipboard_text(clip):
    out = run_js('paste.js', clipboard=clip, click='paste')
    assert out['submitted'] is False and out['url']['value'] == ''
    assert 'doesn’t hold a YouTube link' in out['paste-hint']['text']


@needs_node
def test_paste_button_empty_denied_and_unsupported():
    out = run_js('paste.js', clipboard='', click='paste')
    assert out['submitted'] is False and 'empty' in out['paste-hint']['text']
    out = run_js('paste.js', clipboardFails=True, click='paste')
    assert out['submitted'] is False and 'choose Paste' in out['paste-hint']['text']
    assert out['focused'] == 'url'
    out = run_js('paste.js', noClipboard=True)
    assert out['paste']['hidden'] is True                    # no API, no button
