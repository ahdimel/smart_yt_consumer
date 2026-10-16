"""§11 H: email. Resend is faked by a local HTTP server, so the real transport is exercised."""
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from server import cli, mail
from server.config import RETENTION, Settings

from .conftest import CANARY, Env, summary_md, url, vid


class FakeResend:
    """Answers POST /emails with the next queued status (default 200) and records each call."""

    def __init__(self):
        self.calls, self.statuses = [], []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                raw = self.rfile.read(int(self.headers['content-length']))
                status = outer.statuses.pop(0) if outer.statuses else 200
                outer.calls.append({'path': self.path, 'headers': dict(self.headers),
                                    'body': json.loads(raw), 'status': status})
                out = json.dumps({'id': 'em_1'} if status < 300 else {'message': 'no'}).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.httpd.server_port}'
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def delivered(self):
        return [c for c in self.calls if c['status'] < 300]


@pytest.fixture
def resend():
    fake = FakeResend()
    yield fake
    fake.httpd.shutdown()


@pytest.fixture
def renv(tmp_path, resend):
    """An Env whose mailer is the real ResendMailer, pointed at the fake."""
    env = Env(tmp_path / 'test.db')
    env.mailer = mail.ResendMailer('re_test_key', 'desloppify <desloppify@notify.ahdimel.com>',
                                   'hello@ahdimel.com', resend.url)
    env.app = __import__('server.app', fromlist=['create_app']).create_app(
        env.settings, env.clock, env.mailer)
    env.client = TestClient(env.app, base_url='https://testserver')
    return env


def tick(env):
    with env.db() as conn:
        mail.deliver_pending(conn, env.mailer, 'https://testserver', env.clock())


def done_job(env, user, n=1, md=None):
    env.submit(user, url(n))
    return env.summarize(md)


# ── H1–H3, H7: what the email says ───────────────────────────────────────────

def test_done_email(env):                                                        # H1
    u = env.user()
    lease = done_job(env, u)
    [m] = env.mailer.sent
    public_id = env.job(lease['job_id'])['public_id']
    link = f'https://testserver/s/{public_id}'
    assert m['to'] == u.email
    assert m['subject'] == 'Summary: A perfectly ordinary title'
    until = '21 October 2026'                     # T0 + 30 days, in UTC
    for part in (m['html'], m['text']):
        assert 'A perfectly ordinary title' in part and link in part
        assert f'Available until {until}.' in part
    assert f'<a href="{link}">Read the summary</a>' in m['html']
    assert '<' not in m['text']


def test_failed_email(env):                                                      # H2
    u = env.user()
    env.submit(u, url(1))
    env.fail(env.claimed(), 'no_captions')
    [m] = env.mailer.sent
    assert m['to'] == u.email and m['subject'] == "Couldn't summarize your video"
    for part in (m['html'], m['text']):
        assert 'No captions, so nothing to summarize.' in part
        assert "This didn't count against your limit." in part
        # No title exists for a failed job; the request time identifies it instead.
        assert 'sent on 21 September 2026 at' in part


def test_retryable_failure_emails_only_when_final(env):
    u = env.user()
    env.submit(u, url(1))
    env.fail(env.claimed(), 'summarize_failed')
    assert env.mailer.sent == []
    env.clock.advance(5 * 60)
    env.fail(env.claimed(), 'summarize_failed')
    assert len(env.mailer.sent) == 1
    assert 'The summarizer failed on this video.' in env.mailer.sent[0]['text']


def test_title_escaped_in_html_intact_in_text(env):                              # H3
    title = '<script>alert(1)</script> Cats & Dogs'
    done_job(env, env.user(), md=summary_md(title=title))
    [m] = env.mailer.sent
    assert '<script>' not in m['html']
    assert '&lt;script&gt;alert(1)&lt;/script&gt; Cats &amp; Dogs' in m['html']
    assert title in m['text'] and m['subject'] == f'Summary: {title}'


def test_email_carries_title_only(env):                                          # H7
    md = summary_md(title='Plain title', verdict=f'**Skip.** {CANARY}-verdict',
                    body=f'{CANARY}-body claim at `1:02`.\n\n## What the comments contest\n\n'
                         f'- {CANARY}-comment')
    md = md.replace('fluff: 10%', f'fluff: {CANARY}-fluff')
    lease = done_job(env, env.user(), md=md)
    [m] = env.mailer.sent
    blob = m['subject'] + m['html'] + m['text']
    assert CANARY not in blob
    assert vid(1) not in blob and 'youtube' not in blob.lower() and 'youtu.be' not in blob
    assert 'Plain title' in blob and env.job(lease['job_id'])['email_status'] == 'sent'


# ── H4–H6: delivery ─────────────────────────────────────────────────────────

def test_request_shape(renv, resend):
    u = renv.user()
    done_job(renv, u)
    [c] = resend.calls
    assert c['path'] == '/emails'
    assert c['headers']['Authorization'] == 'Bearer re_test_key'
    assert c['headers']['Idempotency-Key'].startswith('job-')
    b = c['body']
    assert b['from'] == 'desloppify <desloppify@notify.ahdimel.com>'
    assert b['reply_to'] == 'hello@ahdimel.com' and b['to'] == [u.email]
    assert set(b) == {'from', 'to', 'reply_to', 'subject', 'html', 'text'}


def test_5xx_is_retried_with_backoff_and_sent_once(renv, resend):                # H4
    resend.statuses = [500, 503]
    lease = done_job(renv, renv.user())
    job = renv.job(lease['job_id'])
    assert job['email_status'] == 'pending' and job['email_attempts'] == 1
    assert job['email_not_before'] == renv.clock() + mail.BACKOFF[0]
    tick(renv)                                       # not due yet: no call
    assert len(resend.calls) == 1
    renv.clock.advance(mail.BACKOFF[0])
    tick(renv)                                       # 503
    assert renv.job(lease['job_id'])['email_status'] == 'pending'
    renv.clock.advance(mail.BACKOFF[1])
    tick(renv)                                       # 200
    renv.clock.advance(24 * 3600)
    tick(renv)
    tick(renv)
    assert [c['status'] for c in resend.calls] == [500, 503, 200]
    assert len(resend.delivered) == 1
    assert renv.job(lease['job_id'])['email_status'] == 'sent'
    # every attempt at one email carries the same idempotency key
    assert len({c['headers']['Idempotency-Key'] for c in resend.calls}) == 1


def test_gives_up_after_max_attempts(renv, resend):
    resend.statuses = [500] * 50
    lease = done_job(renv, renv.user())
    for _ in range(20):
        renv.clock.advance(4 * 3600)
        tick(renv)
    job = renv.job(lease['job_id'])
    assert job['email_status'] == 'failed' and len(resend.calls) == mail.MAX_ATTEMPTS


def test_no_reply_to_when_mailing_the_reply_to_address(renv, resend):
    owner = renv.user()
    renv.sql('UPDATE users SET email = ? WHERE id = ?', 'Hello@Ahdimel.com', owner.id)
    done_job(renv, owner)
    [c] = resend.calls
    assert c['body']['to'] == ['Hello@Ahdimel.com'] and 'reply_to' not in c['body']


@pytest.mark.parametrize('status', [400, 401, 403, 422])
def test_4xx_fails_without_retry(renv, resend, status):                          # H5
    resend.statuses = [status]
    lease = done_job(renv, renv.user())
    for _ in range(5):
        renv.clock.advance(3600)
        tick(renv)
    assert len(resend.calls) == 1
    assert renv.job(lease['job_id'])['email_status'] == 'failed'
    admin = renv.user(admin=True)
    usage = renv.client.get('/admin/usage.json', headers=admin.cookie).json()
    assert usage['emails_failed'] == 1
    page = renv.client.get('/admin', headers=admin.cookie).text
    assert 'Emails failed: 1' in page


def test_429_and_network_errors_are_transient(renv, resend):
    resend.statuses = [429]
    lease = done_job(renv, renv.user())
    assert renv.job(lease['job_id'])['email_status'] == 'pending'
    renv.mailer.url = 'http://127.0.0.1:9/emails'          # nothing listens on port 9
    renv.clock.advance(mail.BACKOFF[0])
    tick(renv)
    job = renv.job(lease['job_id'])
    assert job['email_status'] == 'pending' and job['email_attempts'] == 2


def test_coalesced_jobs_get_one_email_each(renv, resend):                        # H6
    a, b, c = renv.user(), renv.user(), renv.user()
    renv.submit(a, url(1))
    renv.submit(b, url(1))
    renv.submit(c, url(2))
    renv.summarize()                                 # video 1: a and b
    for _ in range(3):
        renv.clock.advance(3600)
        tick(renv)
    assert sorted(x['body']['to'][0] for x in resend.calls) == sorted([a.email, b.email])
    links = {x['body']['text'].split('Read the summary: ')[1].split()[0] for x in resend.calls}
    assert len(links) == 2                           # each friend has their own /s/ link


def test_stale_sending_is_reset_and_sent_once(env):
    lease = done_job(env, env.user())
    jid = lease['job_id']
    env.mailer.sent.clear()
    with env.db() as conn:
        conn.execute("UPDATE jobs SET email_status = 'sending', email_claimed_at = ? WHERE id = ?",
                     (env.clock() - 60, jid))
    tick(env)                                        # claimed a minute ago: leave it alone
    assert env.mailer.sent == [] and env.job(jid)['email_status'] == 'sending'
    env.clock.advance(mail.STALE_SENDING)
    tick(env)
    tick(env)
    assert len(env.mailer.sent) == 1 and env.job(jid)['email_status'] == 'sent'


def test_mailer_exception_is_transient(env):
    def boom(*a, **k):
        raise RuntimeError('x')
    env.mailer.send = boom
    lease = done_job(env, env.user())
    assert env.job(lease['job_id'])['email_status'] == 'pending'


def test_no_mailer_leaves_mail_pending(tmp_path):
    env = Env(tmp_path / 'n.db')
    env.app = __import__('server.app', fromlist=['create_app']).create_app(
        env.settings, env.clock)                     # no RESEND_API_KEY in settings
    env.client = TestClient(env.app, base_url='https://testserver')
    assert env.app.state.mailer is None
    lease = done_job(env, env.user())
    assert env.job(lease['job_id'])['email_status'] == 'pending'


def test_resend_mailer_from_settings():
    assert mail.from_settings(Settings()) is None
    m = mail.from_settings(Settings(resend_api_key='re_x', public_origin='https://x.example'))
    assert isinstance(m, mail.ResendMailer) and m.url == 'https://api.resend.com/emails'
    with pytest.raises(ValueError):
        mail.from_settings(Settings(resend_api_key='re_x'))
    assert 're_secret' not in repr(Settings(resend_api_key='re_secret'))
    assert 'wt-secret' not in repr(Settings(worker_token='wt-secret'))


def test_background_loop_retries(tmp_path, resend, monkeypatch):
    monkeypatch.setattr(mail, 'LOOP_SECONDS', 0.05)
    monkeypatch.setattr(mail, 'BACKOFF', (0,) * 5)
    env = Env(tmp_path / 'loop.db', resend_api_key='re_loop', resend_api_url=resend.url,
              public_origin='https://testserver')
    env.clock = time.time                            # the loop reads the real clock
    from server.app import create_app
    env.app = create_app(env.settings, lambda: int(time.time()))
    resend.statuses = [500]
    with TestClient(env.app, base_url='https://testserver') as client:
        env.client = client
        u = env.user()
        env.submit(u, url(1))
        env.summarize()
        deadline = time.time() + 5
        while len(resend.delivered) < 1 and time.time() < deadline:
            time.sleep(0.05)
    assert [c['status'] for c in resend.calls] == [500, 200]


def test_logs_hold_no_content(renv, resend, caplog):
    caplog.set_level(logging.DEBUG)
    resend.statuses = [500]
    u = renv.user()
    title = f'{CANARY} Title'
    renv.submit(u, f'https://www.youtube.com/watch?v={vid(7)}')
    lease = renv.summarize(summary_md(title=title))
    renv.clock.advance(3600)
    tick(renv)
    public_id = renv.job(lease['job_id'])['public_id']
    renv.client.get(f'/s/{public_id}')
    # The app's logger only: httpx's lines are the test client's, not the server's.
    text = '\n'.join(r.getMessage() for r in caplog.records if r.name == 'server')
    assert f'mail job={lease["job_id"]}' in text
    for leak in (CANARY, vid(7), 'youtube', u.email, public_id, 're_test_key', u.token):
        assert leak not in text


# ── the owner's deliverability check ────────────────────────────────────────

def test_cli_test_email(resend, monkeypatch, capsys):
    monkeypatch.setenv('RESEND_API_KEY', 're_cli')
    monkeypatch.setenv('RESEND_API_URL', resend.url)
    monkeypatch.setenv('PUBLIC_ORIGIN', 'https://desloppify.ahdimel.com')
    assert cli.main(['test-email', '--to', 'someone@example.org']) is None
    assert capsys.readouterr().out.strip() == 'sent (HTTP 200)'
    [c] = resend.calls
    assert c['body']['to'] == ['someone@example.org'] and c['body']['subject'] == 'Test email'
    resend.statuses = [422]
    assert cli.main(['test-email', '--to', 'x@example.org']) == 1
    monkeypatch.delenv('RESEND_API_KEY')
    assert 'not set' in cli.main(['test-email', '--to', 'x@example.org'])


def test_retention_constant_matches_email_date():
    assert RETENTION == 30 * 24 * 3600
