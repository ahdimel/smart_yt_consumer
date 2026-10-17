"""§11 K3–K4: what a full request cycle leaves in the logs and in the repo.

The server runs as production runs it: uvicorn in a subprocess with --no-access-log (Dockerfile),
the real Resend transport pointed at a local fake, and the working directory at the repo root.
The worker runs with the stubs from test_worker.py, also from the repo root. Everything either
of them prints is captured and grepped (K3), and every file under the repo that git doesn't
ignore is checked to be untouched (K4). Needs the server venv; skipped without it.

Run: server/.venv/bin/python -m unittest discover -s tests
"""
import json, os, subprocess, sys, threading, time, unittest, urllib.request
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_worker as tw  # noqa: E402

try:
    import uvicorn  # noqa: F401  (only to tell whether this is the server venv)
    from server import db, users
except ImportError:          # system python3 without the server venv
    uvicorn = None

ROOT = tw.ROOT
RESEND_KEY = 're_k3_' + 'q' * 30
# Paths drain writes every 15 minutes while it runs beside the tests. Neither the server nor
# the worker writes there, and a drain commit mid-test would otherwise fail K4.
DRAIN_OWNS = ('out/', 'queue/')
AUDIT = os.path.join(ROOT, 'ops', 'audit-app-log')


class FakeResend:
    def __init__(self):
        self.calls = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                outer.calls.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                out = b'{"id": "em_k3"}'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.url = f'http://127.0.0.1:{self.httpd.server_port}'
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def repo_files():
    """Every file under the repo that git doesn't ignore, with its size and mtime."""
    out = subprocess.run(['git', '-C', ROOT, 'ls-files', '-z', '--cached', '--others',
                          '--exclude-standard'], capture_output=True, check=True).stdout
    state = {}
    for rel in out.decode().split('\0'):
        if not rel or rel.startswith(DRAIN_OWNS):
            continue
        try:
            st = os.stat(os.path.join(ROOT, rel))
            state[rel] = (st.st_size, st.st_mtime_ns)
        except FileNotFoundError:
            state[rel] = None
    return state


@unittest.skipIf(uvicorn is None, 'needs the server venv (server/.venv)')
class FullCycle(tw.WorkerCase):
    def setUp(self):
        self.before = repo_files()
        super().setUp()
        self.resend = FakeResend()
        self.addCleanup(self.resend.close)
        self.db_path = os.path.join(self.tmp.name, 'server.db')
        self.base = f'http://127.0.0.1:{tw.closed_port()}'
        self.log_path = os.path.join(self.tmp.name, 'server.log')
        env = dict(os.environ, DB_PATH=self.db_path, WORKER_TOKEN=tw.TOKEN,
                   PUBLIC_ORIGIN=self.base, COOKIE_SECURE='0', RESEND_API_KEY=RESEND_KEY,
                   RESEND_API_URL=self.resend.url, PYTHONDONTWRITEBYTECODE='1')
        port = self.base.rsplit(':', 1)[1]
        self.log_file = open(self.log_path, 'w')
        self.server_proc = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'server.app:create_app', '--factory',
             '--host', '127.0.0.1', '--port', port, '--no-access-log'],
            cwd=ROOT, env=env, stdout=self.log_file, stderr=subprocess.STDOUT)
        self.addCleanup(self.stop_server)
        for _ in range(200):
            try:
                urllib.request.urlopen(self.base + '/healthz', timeout=1)
                break
            except OSError:
                time.sleep(0.05)
        self.write_env(self.base)
        self.users = []
        for name in ('Owner', 'Friend'):
            with closing(db.connect(self.db_path)) as conn:
                uid, token = users.create(conn, name, f'{name.lower()}@example.org', time.time())
                conn.execute('UPDATE users SET welcomed_at = ? WHERE id = ?', (time.time(), uid))
            self.users.append(token)

    def stop_server(self):
        if self.server_proc.poll() is None:
            self.server_proc.terminate()
            self.server_proc.wait(timeout=10)
        self.log_file.close()

    def request(self, path, data=None, token=None, cookie=None):
        headers = {'Content-Type': 'application/json'} if data is not None else {}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if cookie:
            headers['Cookie'] = 'session=' + cookie
        req = urllib.request.Request(self.base + path, headers=headers,
                                     data=json.dumps(data).encode() if data is not None else None)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()

    def wait_for_mail(self, n):
        deadline = time.time() + 10
        while len(self.resend.calls) < n and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(len(self.resend.calls), n)

    def test_cycle_logs_hold_no_content_and_repo_is_untouched(self):           # K3, K4
        owner, friend = self.users
        # The invite link, then the paste box's JSON submit, as the friend's browser does it.
        self.request('/u/' + owner)
        _, body = self.request('/api/requests', {'url': tw.URL}, token=owner)
        public_id = json.loads(body)['id']

        p = subprocess.run([sys.executable, tw.WORKER], env=self.env(), cwd=ROOT,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.wait_for_mail(1)
        status, page = self.request('/s/' + public_id)
        self.assertEqual(status, 200)
        self.assertIn(tw.CANARY, page)                 # the content exists, so its absence counts
        self.assertIn(tw.CANARY, self.resend.calls[0]['subject'])

        # A second friend gets a cache hit: submit, email, page.
        _, body = self.request('/api/requests', {'url': f'https://youtu.be/{tw.VID}'}, token=friend)
        hit_id = json.loads(body)['id']
        self.wait_for_mail(2)
        self.assertEqual(self.request('/s/' + hit_id)[0], 200)
        self.assertEqual(self.request('/', cookie=friend)[0], 200)

        self.stop_server()
        with open(self.log_path) as f:
            server_log = f.read()
        self.assertIn('complete job=1', server_log)
        self.assertIn('mail job=2 attempt=1 outcome=sent', server_log)
        self.assertIn('job 1: complete acknowledged', p.stderr)
        logs = {'server': server_log, 'worker': p.stdout + p.stderr}
        for name, text in logs.items():
            self.assertNotIn('Traceback', text, name)
            for leak in (tw.CANARY, 'ZZCANARY', 'Canary Channel', tw.VID, 'youtube', 'youtu.be',
                         public_id, hit_id, owner, friend, tw.TOKEN, RESEND_KEY,
                         'owner@example.org', 'friend@example.org'):
                self.assertNotIn(leak, text, (name, leak))

        audit = subprocess.run([AUDIT], input=server_log, capture_output=True, text=True)
        self.assertTrue(audit.stdout.endswith('unknown lines: 0\n'), audit.stdout)

        self.assertEqual(self.job_dirs(), [])
        self.assertEqual(repo_files(), self.before)                            # K4


class DefaultPaths(unittest.TestCase):
    def test_default_paths_stay_out_of_the_tree(self):                         # K4
        """The server's database defaults to outside the repo; the worker's work dir defaults
        to .work/, which git ignores. The tests above override both, so check the defaults."""
        from server.config import Settings          # stdlib-only module
        self.assertFalse(os.path.abspath(Settings().db_path).startswith(ROOT + os.sep))
        r = subprocess.run(['git', '-C', ROOT, 'check-ignore', '-q', '.work/1/bundle.md'])
        self.assertEqual(r.returncode, 0)
        with open(tw.WORKER) as f:
            self.assertIn("os.path.join(ROOT, '.work')", f.read())


class AuditAppLog(unittest.TestCase):
    def test_flags_unknown_lines_without_echoing_them(self):
        leak = f'submit job=3 title={tw.CANARY} https://youtu.be/{tw.VID}'
        lines = ['2026-10-17 00:00:00,000 INFO submit job=3 user=1 status=queued',
                 json.dumps({'message': '2026-10-17 00:00:01,000 INFO purge summaries=2 jobs=5'}),
                 'INFO:     Application startup complete.',
                 '2026-10-17 00:00:02,000 INFO ' + leak,
                 'Traceback (most recent call last):']
        r = subprocess.run([AUDIT], input='\n'.join(lines) + '\n', capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('FLAG  input line 4: ', r.stdout)
        self.assertIn('youtube=yes, url=yes, traceback=no', r.stdout)
        self.assertIn('FLAG  input line 5: ', r.stdout)
        self.assertIn('traceback=yes', r.stdout)
        self.assertTrue(r.stdout.endswith('unknown lines: 2\n'))
        for word in (tw.CANARY, 'ZZCANARY', tw.VID, 'youtu.be', 'title='):
            self.assertNotIn(word, r.stdout)


if __name__ == '__main__':
    unittest.main()
