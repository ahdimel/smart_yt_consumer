"""Fixtures: a temp SQLite, an injectable clock, a fake mailer, and protocol helpers.

Run: server/.venv/bin/pytest server/tests
"""
import os
import sys
from contextlib import closing
from dataclasses import dataclass

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient  # noqa: E402

from server import db, users  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import Settings  # noqa: E402

T0 = 1_790_000_000
WORKER_TOKEN = 'worker-' + 'x' * 40
ORIGIN = 'https://testserver'
USAGE = {'input_tokens': 100, 'cache_creation_input_tokens': 20,
         'cache_read_input_tokens': 30, 'output_tokens': 50}
USAGE_TOTAL = 200
CANARY = 'ZZCANARY-7f3a'


def vid(n):
    return f'v{n:010d}'


def url(n):
    return f'https://youtu.be/{vid(n)}'


def summary_md(title='A perfectly ordinary title', verdict='**Skim.** Fine.', body='Body text.'):
    return (f'---\nnav: Short\ntitle: {title}\nchannel: Someone\nduration: 10m0s\nviews: 1 view\n'
            f'verdict: {verdict}\nwatchable: ~1 of 10 min\nfluff: 10%\n'
            f'compression: 1,000 → 100 words (10:1)\nadded: 2026-10-16T00:00:00\n---\n\n{body}\n')


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeMailer:
    def __init__(self):
        self.sent = []
        self.outcome = 'sent'

    def send(self, to, subject, html_body, text_body):
        self.sent.append({'to': to, 'subject': subject, 'html': html_body, 'text': text_body})
        return self.outcome


@dataclass
class User:
    id: int
    token: str
    email: str

    @property
    def bearer(self):
        return {'Authorization': f'Bearer {self.token}'}

    @property
    def cookie(self):
        return {'Cookie': f'session={self.token}'}


class Env:
    def __init__(self, path, **settings):
        self.clock = Clock()
        self.mailer = FakeMailer()
        self.settings = Settings(**{'db_path': str(path), 'worker_token': WORKER_TOKEN, **settings})
        self.app = create_app(self.settings, self.clock, self.mailer)
        self.client = TestClient(self.app, base_url=ORIGIN)
        self._n = 0

    # ── data ──────────────────────────────────────────────────────────────
    def db(self):
        return closing(db.connect(self.settings.db_path))

    def user(self, admin=False, welcomed=True, **cols):
        self._n += 1
        email = f'friend{self._n}@example.org'
        with self.db() as conn:
            uid, token = users.create(conn, f'Friend {self._n}', email, self.clock(), admin)
            if welcomed:
                cols['welcomed_at'] = self.clock()
            for k, v in cols.items():
                conn.execute(f'UPDATE users SET {k} = ? WHERE id = ?', (v, uid))
        return User(uid, token, email)

    def job(self, job_id):
        with self.db() as conn:
            return conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()

    def job_by_public(self, public_id):
        with self.db() as conn:
            return conn.execute('SELECT * FROM jobs WHERE public_id = ?', (public_id,)).fetchone()

    def sql(self, q, *args):
        with self.db() as conn:
            return conn.execute(q, args).fetchall()

    def set(self, **cols):
        with self.db() as conn:
            for k, v in cols.items():
                conn.execute(f'UPDATE settings SET {k} = ? WHERE id = 1', (v,))

    # ── friend side ───────────────────────────────────────────────────────
    def submit(self, user, text, headers=None):
        return self.client.post('/api/requests', json={'url': text},
                                headers={**user.bearer, **(headers or {})})

    # ── worker side ───────────────────────────────────────────────────────
    W = {'Authorization': f'Bearer {WORKER_TOKEN}'}

    def claim(self):
        return self.client.post('/worker/claim', json={'version': 'test'}, headers=self.W)

    def claimed(self):
        r = self.claim()
        assert r.status_code == 200, r.text
        return r.json()

    def complete(self, lease, md=None, usage=USAGE, cost=0.5):
        return self.client.post(
            f'/worker/jobs/{lease["job_id"]}/complete', headers=self.W,
            json={'lease_id': lease['lease_id'], 'md': md or summary_md(), 'usage': usage,
                  'cost_usd': cost, 'model': 'claude-opus-5'})

    def fail(self, lease, code, usage=None, cost=0):
        return self.client.post(
            f'/worker/jobs/{lease["job_id"]}/fail', headers=self.W,
            json={'lease_id': lease['lease_id'], 'error_code': code, 'usage': usage or {},
                  'cost_usd': cost})

    def summarize(self, md=None):
        """Claim the next job and complete it."""
        lease = self.claimed()
        r = self.complete(lease, md)
        assert r.status_code == 200, r.text
        return lease


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path / 'test.db')


@pytest.fixture
def make_env(tmp_path):
    return lambda **settings: Env(tmp_path / 'test.db', **settings)
