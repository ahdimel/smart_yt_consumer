"""The worker against the real M1 server under uvicorn, with the stubs from test_worker.py.

test_worker.py proves the worker's behaviour against a fake; this proves the two sides agree on
the protocol: payloads, usage columns, lease loss (409), invalid output (422) and retries.
Needs the server venv; skipped without it.

Run: server/.venv/bin/python -m unittest discover -s tests
"""
import os, sys, threading, time, unittest
from contextlib import closing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_worker as tw  # noqa: E402

try:
    import json as _json
    import urllib.request
    import uvicorn
    from server import db, users
    from server.app import create_app
    from server.config import Settings
except ImportError:          # system python3 without the server venv
    uvicorn = None


@unittest.skipIf(uvicorn is None, 'needs the server venv (server/.venv)')
class RealServer(tw.WorkerCase):
    def setUp(self):
        super().setUp()
        port = tw.closed_port()
        self.base = f'http://127.0.0.1:{port}'
        self.db_path = os.path.join(self.tmp.name, 'server.db')
        app = create_app(Settings(db_path=self.db_path, worker_token=tw.TOKEN,
                                  public_origin=self.base, cookie_secure=False))
        self.uv = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port,
                                                log_level='warning', access_log=False))
        threading.Thread(target=self.uv.run, daemon=True).start()
        for _ in range(100):
            if self.uv.started:
                break
            time.sleep(0.05)
        self.addCleanup(lambda: setattr(self.uv, 'should_exit', True))
        self.write_env(self.base)
        with closing(db.connect(self.db_path)) as conn:
            uid, self.user_token = users.create(conn, 'Owner', 'owner@example.org', time.time())
            conn.execute('UPDATE users SET welcomed_at = ? WHERE id = ?', (time.time(), uid))

    def submit(self):
        req = urllib.request.Request(
            self.base + '/api/requests', data=_json.dumps({'url': tw.URL}).encode(),
            headers={'Authorization': 'Bearer ' + self.user_token,
                     'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=10) as r:
            self.assertLess(r.status, 300)
        return self.job()['id']

    def job(self):
        with closing(db.connect(self.db_path)) as conn:
            return conn.execute('SELECT * FROM jobs ORDER BY id DESC LIMIT 1').fetchone()

    def summaries(self):
        with closing(db.connect(self.db_path)) as conn:
            return conn.execute('SELECT video_id, md, title FROM summaries').fetchall()

    def test_end_to_end(self):                                                 # F1, real
        jid = self.submit()
        p = self.run_worker()
        self.assertEqual(p.returncode, 0, p.stderr)
        j = self.job()
        self.assertEqual((j['id'], j['status'], j['attempts']), (jid, 'done', 1))
        self.assertEqual((j['input_tokens'], j['cache_write_tokens'], j['cache_read_tokens'],
                          j['output_tokens']), (7, 12000, 300, 4321))
        self.assertAlmostEqual(j['cost_usd'], 0.42)
        self.assertEqual(j['model'], 'claude-opus-5-5')
        [(vid, md, title)] = self.summaries()
        self.assertEqual((vid, title), (tw.VID, tw.CANARY))
        self.assertTrue(md.startswith('---\n'))
        self.assertEqual(self.job_dirs(), [])
        self.assertIn(f'job {jid}: complete acknowledged', p.stderr)

    def test_permanent_failure(self):                                          # F4, real
        self.scenario(info=dict(tw.INFO, duration=4 * 3600))
        self.submit()
        self.run_worker()
        j = self.job()
        self.assertEqual((j['status'], j['error_code']), ('failed', 'too_long'))
        self.assertFalse(self.claude_ran())

    def test_retryable_failure_requeued(self):                                 # F6, real
        self.scenario(meta_error='HTTP Error 429: Too Many Requests')
        self.submit()
        self.run_worker()
        j = self.job()
        self.assertEqual((j['status'], j['error_code']), ('queued', 'rate_limited'))
        self.assertGreater(j['not_before'], time.time())

    def test_server_rejects_front_matter(self):                                # E6 ↔ F
        # clean.py accepts an empty title; the server does not, and answers 422
        self.scenario(md=tw.SUMMARY.replace(f'title: {tw.CANARY}', 'title:'))
        self.submit()
        p = self.run_worker()
        j = self.job()
        self.assertEqual((j['status'], j['error_code']), ('queued', 'invalid_output'))
        self.assertEqual(j['output_tokens'], 4321)      # tokens recorded via fail
        self.assertEqual(self.summaries(), [])
        self.assertIn('422', p.stderr)

    def test_lease_lost_mid_job(self):                                         # E3/E5 ↔ F
        self.scenario(claude_sleep=3)
        self.submit()
        import subprocess
        w = subprocess.Popen([sys.executable, tw.WORKER], env=self.env(), cwd=self.tmp.name,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        marker = os.path.join(self.stubs, 'claude.marker')
        for _ in range(100):
            if os.path.exists(marker):
                break
            time.sleep(0.05)
        # the Mac "slept": the lease expired and someone else claimed the job
        with closing(db.connect(self.db_path)) as conn:
            conn.execute('UPDATE jobs SET lease_until = 0')
        req = urllib.request.Request(self.base + '/worker/claim', data=b'{}', method='POST',
                                     headers={'Authorization': 'Bearer ' + tw.TOKEN})
        with urllib.request.urlopen(req, timeout=10) as r:
            self.assertEqual(r.status, 200)
        out, err = w.communicate(timeout=30)
        self.assert_clean_log(out + err)
        self.assertIn('409', err)
        self.assertEqual(self.summaries(), [])
        self.assertEqual(self.job()['attempts'], 2)
        self.assertEqual(self.job_dirs(), [])


if __name__ == '__main__':
    unittest.main()
