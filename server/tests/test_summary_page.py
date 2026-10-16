"""§11 I: the summary page at /s/<public_id>. The renderer's own cases are tests/test_render.py;
these go through the server, where the page, its headers and its lifetime are decided."""
import base64
import re

from server import app as app_module
from server.config import RETENTION

from .conftest import summary_md, url, vid

TAG = re.compile(r'<[^>]*>')


def tags(s):
    return TAG.findall(s)


def published(env, md=None, n=1, user=None):
    """Submit, summarize, and return the job's public_id."""
    env.submit(user or env.user(), url(n))
    lease = env.summarize(md)
    return env.job(lease['job_id'])['public_id']


def test_headers(env):                                                           # I1
    r = env.client.get(f'/s/{published(env)}')
    assert r.status_code == 200 and r.headers['content-type'].startswith('text/html')
    assert r.headers['content-security-policy'] == app_module.CSP
    assert "script-src 'self'" in r.headers['content-security-policy']
    assert r.headers['x-robots-tag'] == 'noindex'
    assert r.headers['referrer-policy'] == 'no-referrer'
    assert r.headers['cache-control'] == 'no-store'


def test_needs_no_login(env):                                                    # D3
    pid = published(env)
    env.client.cookies.clear()
    r = env.client.get(f'/s/{pid}', headers={'Cookie': 'session=nonsense'})
    assert r.status_code == 200 and 'A perfectly ordinary title' in r.text


def test_unknown_is_404(env):                                                    # I2
    published(env)
    for pid in ('A' * 22, 'x', 'A' * 200, '..%2F..%2Fetc', vid(1)):
        r = env.client.get(f'/s/{pid}')
        assert r.status_code == 404, pid
        assert 'title' not in r.text.lower() or '<title>Not found.</title>' in r.text


def test_unfinished_and_failed_jobs_are_404(env):
    u = env.user()
    env.submit(u, url(1))
    queued = env.sql('SELECT public_id FROM jobs')[0]['public_id']
    assert env.client.get(f'/s/{queued}').status_code == 404
    env.fail(env.claimed(), 'no_captions')
    assert env.client.get(f'/s/{queued}').status_code == 404


def test_expired_is_410(env):                                                    # I2
    pid = published(env)
    env.clock.advance(RETENTION - 1)
    assert env.client.get(f'/s/{pid}').status_code == 200
    env.clock.advance(1)
    assert env.client.get(f'/s/{pid}').status_code == 410


def test_purged_is_410(env):
    """M5's purge deletes the summary and nulls jobs.video_id; either way the link is gone."""
    a, b = published(env, n=1), published(env, n=2)
    env.sql('DELETE FROM summaries WHERE video_id = ?', vid(1))
    env.sql('UPDATE jobs SET video_id = NULL WHERE public_id = ?', b)
    assert env.client.get(f'/s/{a}').status_code == 410
    assert env.client.get(f'/s/{b}').status_code == 410


def test_refreshed_cache_does_not_revive_an_old_link(env):
    old = published(env)
    env.clock.advance(RETENTION + 1)                 # summary expired; a new request redoes it
    assert env.client.get(f'/s/{old}').status_code == 410
    new = published(env)
    assert env.client.get(f'/s/{new}').status_code == 200
    assert env.client.get(f'/s/{old}').status_code == 410


def test_cache_hit_link_ends_with_the_summary(env):
    first = published(env)
    env.clock.advance(RETENTION - 100)
    env.submit(env.user(), url(1))                   # cache hit near the end of the window
    hit = env.sql('SELECT public_id FROM jobs WHERE cache_hit = 1')[0]['public_id']
    assert env.client.get(f'/s/{hit}').status_code == 200
    env.clock.advance(100)
    assert env.client.get(f'/s/{hit}').status_code == 410
    assert env.client.get(f'/s/{first}').status_code == 410


def test_public_id_is_random_128_bits(env):                                      # I3
    u = env.user(daily_limit=100, weekly_limit=100)
    for n in range(1, 41):
        env.submit(u, url(n))                        # same clock: time can't distinguish them
    rows = env.sql('SELECT id, public_id, created_at FROM jobs')
    ids = [r['public_id'] for r in rows]
    assert len(set(ids)) == len(ids) == 40
    for r in rows:
        raw = base64.urlsafe_b64decode(r['public_id'] + '==')
        assert len(raw) >= 16
        assert str(r['id']) != r['public_id'] and str(r['created_at']) not in r['public_id']
    # no shared prefix that would betray a counter or timestamp
    assert len({i[:4] for i in ids}) > 30


def test_hostile_markdown_stays_inert(env):                                      # I4–I6
    body = ('[click](javascript:alert(1)) and [x](" onmouseover="alert(1)) and '
            '<img src=x onerror=alert(1)> and <script>alert(2)</script>\n\n'
            '## <svg onload=alert(3)>\n\n- [y](data:text/html,<script>alert(4)</script>)')
    md = summary_md(title='<img src=x onerror=alert(5)>', verdict='"><script>alert(6)</script>',
                    body=body).replace('channel: Someone', 'channel: <b onclick=alert(7)>')
    r = env.client.get(f'/s/{published(env, md)}')
    assert r.status_code == 200
    markup = ' '.join(tags(r.text))
    for bad in ('javascript:', 'onmouseover', 'onerror', 'onload', 'onclick', 'data:text'):
        assert bad not in markup, bad
    assert '<script>' not in r.text and '<img' not in r.text
    assert re.findall(r'<script[^>]*>', r.text) == ['<script src="/static/summary.js" defer>']
    assert '&lt;img src=x onerror=alert(5)&gt;' in r.text   # the title, escaped, as text
    assert 'click' in r.text                                # link text survives as text


def test_links_and_timestamp_chips(env):                                         # I7
    body = ('See [the paper](https://example.org/p?a=1&b=2). He says it at `14:32`, '
            'again at `1:02:03`, and `x < y` is code.')
    r = env.client.get(f'/s/{published(env, summary_md(body=body))}')
    assert '<a href="https://example.org/p?a=1&amp;b=2">the paper</a>' in r.text
    assert (f'<a class="ts" href="https://www.youtube.com/watch?v={vid(1)}&amp;t=872s">'
            '14:32</a>') in r.text
    assert f'watch?v={vid(1)}&amp;t=3723s">1:02:03</a>' in r.text
    assert '<span class="mono">x &lt; y</span>' in r.text
    assert f'href="https://youtu.be/{vid(1)}"' in r.text


def test_contest_section_styled(env):                                            # I8
    body = 'Claim.\n\n## What the comments contest\n\n- A correction at `2:10`.'
    r = env.client.get(f'/s/{published(env, summary_md(body=body))}')
    assert '<section class="contested"><h3>What the comments contest</h3>' in r.text
    css = env.client.get('/static/summary.css').text
    assert '.contested{' in css and '.contested h3{' in css


def test_one_line_summary(env):                                                  # I9
    body = 'This video contains one claim: X. Nothing else survives.'
    r = env.client.get(f'/s/{published(env, summary_md(body=body))}')
    assert f'<p>{body}</p>' in r.text
    for empty in ('<ul></ul>', '<section class="contested">', '<h3></h3>', '<p></p>'):
        assert empty not in r.text


def test_save_as_pdf_and_print_stylesheet(env):                                  # I10
    r = env.client.get(f'/s/{published(env)}')
    assert '<button type="button" id="save-pdf" class="save" hidden>Save as PDF</button>' in r.text
    assert 'style=' not in r.text and '<style' not in r.text   # CSP: no inline style either
    js = env.client.get('/static/summary.js')
    assert js.status_code == 200 and js.headers['content-type'].startswith('text/javascript')
    assert 'window.print()' in js.text and "getElementById('save-pdf')" in js.text
    css = env.client.get('/static/summary.css').text
    printing = css[css.index('@media print'):]
    hidden = re.search(r'\n\s*([^{}]+)\{display:none', printing).group(1)
    for cls in ('.bar', '.save', '.src'):
        assert cls in hidden
    # nothing in print mode clips the summary
    assert 'overflow:hidden' not in printing and 'max-height' not in printing
    assert '.wrap{max-width:none' in printing


def test_expired_page_shows_no_title(env):                                       # I11
    md = summary_md(title='Very Distinctive Title', body='Distinctive body.')
    pid = published(env, md)
    env.clock.advance(RETENTION)
    r = env.client.get(f'/s/{pid}')
    assert r.status_code == 410
    assert 'Distinctive' not in r.text and vid(1) not in r.text
    assert 'expired' in r.text
    assert r.headers['x-robots-tag'] == 'noindex'


def test_static_files(env):
    assert env.client.get('/static/app.css').status_code == 200
    for name in ('nope.css', '..%2Fapp.py', 'summary.html'):
        assert env.client.get(f'/static/{name}').status_code == 404


def test_healthz_answers_get_and_head(env):
    """M3's done check is `curl -I https://desloppify.ahdimel.com/healthz`, a HEAD request."""
    assert env.client.get('/healthz').json() == {'ok': True}
    assert env.client.head('/healthz').status_code == 200
