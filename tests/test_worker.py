"""The Mac worker against a fake server, with stub yt-dlp and claude first on PATH (§11 F).

The fake server answers like server/protocol.py and records every request. The stubs record
their argv, and the claude stub drops a marker file, so a test can prove it never ran.
tests/test_worker_server.py plays the same worker against the real server.

Run: python3 -m unittest discover -s tests
"""
import fcntl, json, os, re, signal, socket, subprocess, sys, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKER = os.path.join(ROOT, 'worker')
sys.path.insert(0, ROOT)
from server.codes import CODES  # noqa: E402  (stdlib-only module)

TOKEN = 'test-worker-' + 'k' * 30
VID = 'Zq3CanaryV1'
URL = f'https://www.youtube.com/watch?v={VID}'
CANARY = 'ZZCANARY Title Of The Video'
USAGE = {'input_tokens': 7, 'cache_creation_input_tokens': 12000,
         'cache_read_input_tokens': 300, 'output_tokens': 4321,
         'server_tool_use': {'web_search_requests': 0}}

SUMMARY = (f'---\nnav: Canary\ntitle: {CANARY}\nchannel: Canary Channel\nduration: 10m0s\n'
           'views: 1 view\nverdict: **Skim.** Fine.\nwatchable: ~1 of 10 min\nfluff: 10%\n'
           'compression: 1,000 → 100 words (10:1)\nadded: 2026-01-01T00:00:00\n---\n\n'
           'The video says one thing at `01:00`.\n')

INFO = {'id': VID, 'title': CANARY, 'channel': 'Canary Channel', 'channel_id': 'UCx',
        'duration': 600, 'upload_date': '20261001', 'view_count': 1, 'description': 'd',
        'availability': 'public', 'live_status': 'not_live', 'is_live': False, 'age_limit': 0,
        'subtitles': {'en': [{}]}, 'automatic_captions': {'en': [{}], 'fr': [{}]},
        'comments': [{'text': 'A comment long enough to be kept by the bundle filter.',
                      'like_count': 5, 'parent': 'root', 'channel_id': 'UCother'}]}
VTT = (f'WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n{CANARY} transcript line one\n\n'
       '00:01:00.000 --> 00:01:03.000\nand a second line\n')

YTDLP_STUB = r'''
import json, os, sys
S = os.environ['STUB_DIR']
sc = json.load(open(os.path.join(S, 'scenario.json')))
with open(os.path.join(S, 'ytdlp.argv'), 'a') as f:
    f.write(json.dumps(sys.argv[1:]) + '\n')
if '--dump-json' in sys.argv:
    if sc.get('meta_error'):
        sys.stderr.write('ERROR: [youtube] ' + sc['info']['id'] + ': ' + sc['meta_error'] + '\n')
        sys.exit(1)
    print(json.dumps({k: v for k, v in sc['info'].items() if k != 'comments'}))
    sys.exit(0)
o = sys.argv[sys.argv.index('-o') + 1]
if sc.get('fetch_error'):
    sys.stderr.write('ERROR: ' + sc['fetch_error'] + '\n')
if not sc.get('fetch_no_info'):
    json.dump(sc['info'], open(o + '.info.json', 'w'))
for lang in sc.get('vtt', ['en']):
    open(o + '.' + lang + '.vtt', 'w').write(sc['vtt_text'])
'''

CLAUDE_STUB = r'''
import json, os, sys, time
S = os.environ['STUB_DIR']
sc = json.load(open(os.path.join(S, 'scenario.json')))
stdin = sys.stdin.read()
json.dump({'argv': sys.argv[1:], 'cwd': os.getcwd(), 'stdin': stdin, 'pid': os.getpid()},
          open(os.path.join(S, 'claude.marker'), 'w'))
time.sleep(sc.get('claude_sleep', 0))
mode = sc.get('claude', 'ok')
md = sc['md']
if mode == 'fenced':
    md = '```markdown\n' + md + '\n```'
res = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': md,
       'total_cost_usd': 0.42, 'usage': sc['usage'],
       'modelUsage': {'claude-haiku-5-5': {'outputTokens': 3},
                      'claude-opus-5-5': {'outputTokens': 4321}}}
if mode == 'is_error':
    res.update(is_error=True, subtype='error_during_execution')
elif mode == 'empty_result':
    res['result'] = ''
elif mode == 'no_front_matter':
    res['result'] = 'Sure! Here is a summary of the video.'
if mode == 'not_json':
    print('Error: something went wrong')
elif mode != 'empty_stdout':
    print(json.dumps(res))
'''


class FakeServer:
    """The worker protocol as server/protocol.py answers it, with scriptable statuses."""

    def __init__(self):
        self.jobs, self.requests = [], []
        self.status = {'complete': [], 'fail': []}     # popped per call; default 200
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])) or b'{}')
                outer.requests.append((self.path, body, self.headers.get('Authorization')))
                if self.headers.get('Authorization') != 'Bearer ' + TOKEN:
                    return self.reply(401)
                if self.path == '/worker/claim':
                    return self.reply(200, outer.jobs.pop(0)) if outer.jobs else self.reply(204)
                kind = self.path.rsplit('/', 1)[-1]
                q = outer.status.get(kind, [])
                self.reply(q.pop(0) if q else 200, {'ok': True})

            def reply(self, status, obj=None):
                data = json.dumps(obj).encode() if obj is not None else b''
                self.send_response(status)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}'
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def add_job(self, job_id=7, **kw):
        job = {'job_id': job_id, 'lease_id': f'lease-{job_id}', 'lease_until': 0, 'attempt': 1,
               'video_id': VID, 'url': URL, 'max_minutes': 180}
        job.update(kw)
        self.jobs.append(job)
        return job

    def reports(self, kind=None):
        return [(p, b) for p, b, _ in self.requests
                if p != '/worker/claim' and (kind is None or p.endswith('/' + kind))]

    def claims(self):
        return [b for p, b, _ in self.requests if p == '/worker/claim']

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class WorkerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.stubs, self.bin, self.work = (os.path.join(t, n) for n in ('stubs', 'bin', 'work'))
        os.makedirs(self.stubs)
        os.makedirs(self.bin)
        for name, src in (('yt-dlp', YTDLP_STUB), ('claude', CLAUDE_STUB)):
            p = os.path.join(self.bin, name)
            with open(p, 'w') as f:
                f.write(f'#!{sys.executable}\n{src}')
            os.chmod(p, 0o755)
        self.server = FakeServer()
        self.addCleanup(self.server.close)
        self.env_file = os.path.join(t, 'env')
        self.write_env(self.server.url)
        self.scenario()

    def tearDown(self):
        self.tmp.cleanup()

    def write_env(self, server_url, mode=0o600):
        with open(self.env_file, 'w') as f:
            f.write(f'WORKER_TOKEN={TOKEN}\nSERVER_URL={server_url}\n')
        os.chmod(self.env_file, mode)

    def scenario(self, **kw):
        sc = {'info': dict(INFO), 'vtt_text': VTT, 'md': SUMMARY, 'usage': USAGE}
        sc.update(kw)
        with open(os.path.join(self.stubs, 'scenario.json'), 'w') as f:
            json.dump(sc, f)

    def env(self, **extra):
        e = dict(os.environ)
        e.update(PATH=self.bin + os.pathsep + e.get('PATH', ''), STUB_DIR=self.stubs,
                 WORKER_ENV_FILE=self.env_file, WORKER_WORK_DIR=self.work)
        e.update(extra)
        return e

    def run_worker(self, timeout=60, **extra):
        p = subprocess.run([sys.executable, WORKER], env=self.env(**extra), cwd=self.tmp.name,
                           capture_output=True, text=True, timeout=timeout)
        self.assert_clean_log(p.stdout + p.stderr)
        return p

    def assert_clean_log(self, text):                                          # F15
        self.assertNotIn('Traceback', text)
        for s in (VID, 'youtube.com', 'youtu.be', 'ZZCANARY', 'Canary Channel', TOKEN):
            self.assertNotIn(s, text)

    def claude_ran(self):
        return os.path.exists(os.path.join(self.stubs, 'claude.marker'))

    def claude_call(self):
        with open(os.path.join(self.stubs, 'claude.marker')) as f:
            return json.load(f)

    def ytdlp_calls(self):
        p = os.path.join(self.stubs, 'ytdlp.argv')
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(line) for line in f]

    def job_dirs(self):
        if not os.path.isdir(self.work):
            return []
        return [n for n in os.listdir(self.work) if not n.startswith('.')]

    def only_report(self):
        reps = self.server.reports()
        self.assertEqual(len(reps), 1, reps)
        return reps[0]

    def assert_failed(self, code, job_id=7):
        path, body = self.only_report()
        self.assertEqual(path, f'/worker/jobs/{job_id}/fail')
        self.assertEqual(body['error_code'], code)
        self.assertEqual(body['lease_id'], f'lease-{job_id}')
        self.assertIn(code, CODES)
        return body


class Success(WorkerCase):
    def test_successful_job(self):                                             # F1
        self.server.add_job()
        p = self.run_worker()
        self.assertEqual(p.returncode, 0)
        path, body = self.only_report()
        self.assertEqual(path, '/worker/jobs/7/complete')
        self.assertEqual(body['lease_id'], 'lease-7')
        self.assertEqual(body['usage'], USAGE)          # passed through untouched
        self.assertEqual(body['cost_usd'], 0.42)
        self.assertEqual(body['model'], 'claude-opus-5-5')
        self.assertTrue(body['md'].startswith('---\n'))
        self.assertIn(f'title: {CANARY}', body['md'])
        self.assertNotIn('added: 2026-01-01T00:00:00', body['md'])   # stamped by clean.py
        self.assertEqual(self.job_dirs(), [])
        self.assertEqual(len(self.server.claims()), 2)  # the job, then 204
        self.assertTrue(self.server.claims()[0]['version'])
        self.assertIn('job 7', p.stderr)
        self.assertIn('out=4321', p.stderr)

    def test_bundle_reaches_claude(self):
        self.server.add_job()
        self.run_worker()
        stdin = self.claude_call()['stdin']
        self.assertTrue(stdin.startswith('=== VIDEO ==='))
        self.assertIn('transcript line one', stdin)
        self.assertIn('A comment long enough', stdin)

    def test_code_fence_stripped(self):                                        # F8
        self.scenario(claude='fenced')
        self.server.add_job()
        self.run_worker()
        path, body = self.only_report()
        self.assertTrue(path.endswith('/complete'))
        self.assertTrue(body['md'].startswith('---\n'))
        self.assertNotIn('```', body['md'])

    def test_drains_queue_in_one_run(self):
        self.server.add_job(7)
        self.server.add_job(8)
        self.run_worker()
        self.assertEqual([p for p, _ in self.server.reports()],
                         ['/worker/jobs/7/complete', '/worker/jobs/8/complete'])
        self.assertEqual(self.job_dirs(), [])

    def test_nothing_to_do_is_silent(self):
        p = self.run_worker()
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stderr, '')
        self.assertEqual(len(self.server.claims()), 1)


class Summarize(WorkerCase):
    def test_claude_argv(self):                                                # F13 (D8)
        self.server.add_job()
        self.run_worker()
        call = self.claude_call()
        argv = call['argv']
        with open(os.path.join(ROOT, 'prompts', 'summarize.md')) as f:
            prompt = f.read().rstrip('\n')
        self.assertEqual(argv[:2], ['-p', prompt])      # the prompt before any variadic flag
        self.assertEqual(argv[argv.index('--output-format') + 1], 'json')
        self.assertIn('--no-session-persistence', argv)
        self.assertEqual(argv[argv.index('--model') + 1], 'opus')
        self.assertEqual(argv[argv.index('--effort') + 1], 'high')
        self.assertEqual(argv[argv.index('--disallowed-tools') + 1], drain_disallowed())
        self.assertEqual(argv[-2], '--disallowed-tools')  # nothing after the variadic flag
        self.assertNotIn('--tools', argv)                 # M0's lean flags are shelved
        self.assertEqual(os.path.realpath(call['cwd']), os.path.realpath(ROOT))

    def test_cap_kills_hung_claude(self):                                      # F2
        self.scenario(claude_sleep=30)
        self.server.add_job()
        t0 = time.time()
        self.run_worker(SUMMARIZE_CAP='1')
        self.assertLess(time.time() - t0, 15)
        self.assert_failed('summarize_failed')
        self.assertFalse(alive(self.claude_call()['pid']))
        self.assertEqual(self.job_dirs(), [])

    def test_untrustworthy_output(self):                                       # F7
        for mode in ('is_error', 'empty_result', 'not_json', 'empty_stdout'):
            with self.subTest(mode=mode):
                self.server.requests.clear()
                self.scenario(claude=mode)
                self.server.add_job()
                self.run_worker()
                body = self.assert_failed('summarize_failed')
                if mode in ('is_error', 'empty_result'):     # tokens were spent: report them
                    self.assertEqual(body['usage'], USAGE)
                    self.assertEqual(body['cost_usd'], 0.42)
                self.assertEqual(self.job_dirs(), [])

    def test_no_front_matter_is_invalid_output(self):
        self.scenario(claude='no_front_matter')
        self.server.add_job()
        self.run_worker()
        body = self.assert_failed('invalid_output')
        self.assertEqual(body['usage'], USAGE)

    def test_server_422_becomes_invalid_output(self):
        self.server.status['complete'] = [422]
        self.server.add_job()
        self.run_worker()
        reps = self.server.reports()
        self.assertEqual([p for p, _ in reps],
                         ['/worker/jobs/7/complete', '/worker/jobs/7/fail'])
        self.assertEqual(reps[1][1]['error_code'], 'invalid_output')
        self.assertEqual(reps[1][1]['usage'], USAGE)
        self.assertEqual(self.job_dirs(), [])

    def test_server_409_drops_result(self):
        self.server.status['complete'] = [409]
        self.server.add_job()
        p = self.run_worker()
        self.assertEqual(len(self.server.reports()), 1)
        self.assertEqual(self.job_dirs(), [])
        self.assertIn('dropped', p.stderr)


class Classify(WorkerCase):
    def test_too_long_skips_claude(self):                                      # F4
        info = dict(INFO, duration=181 * 60)
        self.scenario(info=info)
        self.server.add_job(max_minutes=180)
        self.run_worker()
        self.assert_failed('too_long')
        self.assertFalse(self.claude_ran())
        self.assertEqual(len(self.ytdlp_calls()), 1)   # metadata only: no subs, no comments
        self.assertEqual(self.job_dirs(), [])

    def test_exactly_at_limit_runs(self):
        self.scenario(info=dict(INFO, duration=180 * 60))
        self.server.add_job(max_minutes=180)
        self.run_worker()
        self.assertTrue(self.only_report()[0].endswith('/complete'))

    def test_no_english_captions(self):                                        # F5
        self.scenario(info=dict(INFO, subtitles={'de': [{}]},
                                automatic_captions={'fr': [{}], 'en-fr': [{}]}))
        self.server.add_job()
        self.run_worker()
        self.assert_failed('no_captions')
        self.assertFalse(self.claude_ran())
        self.assertEqual(len(self.ytdlp_calls()), 1)

    def test_live_and_upcoming(self):
        for status in ('is_live', 'is_upcoming', 'post_live'):
            with self.subTest(status=status):
                self.server.requests.clear()
                self.scenario(info=dict(INFO, live_status=status, duration=None))
                self.server.add_job()
                self.run_worker()
                self.assert_failed('live_or_upcoming')
                self.assertFalse(self.claude_ran())

    def test_availability_metadata(self):
        for avail, code in (('private', 'unavailable'), ('subscriber_only', 'members_only'),
                            ('premium_only', 'members_only')):
            with self.subTest(avail=avail):
                self.server.requests.clear()
                self.scenario(info=dict(INFO, availability=avail))
                self.server.add_job()
                self.run_worker()
                self.assert_failed(code)

    def test_ytdlp_error_strings(self):                                        # F6
        cases = [
            ('Private video. Sign in if you\'ve been granted access to this video',
             'unavailable', False),
            ('Video unavailable. This video has been removed by the uploader', 'unavailable', False),
            ('Video unavailable. The uploader has not made this video available in your country',
             'unavailable', False),
            ('Join this channel to get access to members-only content like this video, and '
             'other exclusive perks.', 'members_only', False),
            ('Sign in to confirm your age. This video may be inappropriate for some users.',
             'age_restricted', False),
            ('This live event will begin in 3 hours.', 'live_or_upcoming', False),
            ('Premieres in 2 days', 'live_or_upcoming', False),
            ('Unable to download API page: HTTP Error 429: Too Many Requests', 'rate_limited', True),
            ('Sign in to confirm you’re not a bot. Use --cookies-from-browser',
             'rate_limited', True),
            ('Unable to download webpage: <urlopen error [Errno 8] nodename nor servname>',
             'fetch_failed', True),
        ]
        for msg, code, retryable in cases:
            with self.subTest(code=code, msg=msg[:30]):
                self.server.requests.clear()
                self.scenario(meta_error=msg)
                self.server.add_job()
                self.run_worker()
                self.assert_failed(code)
                self.assertEqual(CODES[code].max_attempts > 1, retryable)
                self.assertFalse(self.claude_ran())

    def test_subtitle_fetch_rate_limited(self):
        self.scenario(vtt=[], fetch_error='Unable to download video subtitles for '
                      '\'en\': HTTP Error 429: Too Many Requests')
        self.server.add_job(7)
        self.server.add_job(8)
        self.run_worker()
        self.assert_failed('rate_limited')        # and job 8 waits for the next run
        self.assertEqual(len(self.server.claims()), 1)
        self.assertEqual(self.job_dirs(), [])

    def test_subtitles_missing_after_fetch(self):
        self.scenario(vtt=[])
        self.server.add_job()
        self.run_worker()
        self.assert_failed('fetch_failed')
        self.assertFalse(self.claude_ran())

    def test_info_missing_after_fetch(self):
        self.scenario(fetch_no_info=True)
        self.server.add_job()
        self.run_worker()
        self.assert_failed('fetch_failed')


class Inputs(WorkerCase):
    def test_ytdlp_gets_only_canonical_url(self):                              # F12
        self.server.add_job()
        self.run_worker()
        calls = self.ytdlp_calls()
        self.assertEqual(len(calls), 2)
        for argv in calls:
            self.assertEqual(argv[-2:], ['--', URL])
            self.assertEqual([a for a in argv if VID in a or 'youtube.com' in a], [URL])
        fetch = calls[1]
        self.assertEqual(fetch[fetch.index('--sub-langs') + 1], 'en,en-US,en-GB,en-orig')
        self.assertTrue(fetch[fetch.index('-o') + 1].startswith(self.work))
        self.assertNotIn(VID, fetch[fetch.index('-o') + 1])
        for argv in calls:
            self.assertTrue(argv[argv.index('--cache-dir') + 1].startswith(self.work))

    def test_non_canonical_url_refused(self):
        for url in (f'{URL}&list=x', f'https://www.youtube.com/watch?v={VID}\n--exec=x',
                    f'https://youtu.be/{VID}', '--exec=touch /tmp/x',
                    'https://www.youtube.com/watch?v=Other123456'):
            with self.subTest(url=url[:40]):
                self.server.requests.clear()
                if os.path.exists(os.path.join(self.stubs, 'ytdlp.argv')):
                    os.remove(os.path.join(self.stubs, 'ytdlp.argv'))
                self.server.add_job(url=url)
                self.run_worker()
                self.assert_failed('unavailable')
                self.assertEqual(self.ytdlp_calls(), [])

    def test_fetch_flags_match_vsum(self):
        import importlib.machinery, importlib.util
        loader = importlib.machinery.SourceFileLoader('worker_mod', WORKER)
        spec = importlib.util.spec_from_loader('worker_mod', loader)
        w = importlib.util.module_from_spec(spec)
        loader.exec_module(w)
        with open(os.path.join(ROOT, 'vsum')) as f:
            vsum = f.read()
        self.assertIn(f'--sub-langs "{w.SUB_LANGS}"', vsum)
        self.assertIn(f'--extractor-args "{w.EXTRACTOR_ARGS}"', vsum)
        self.assertEqual(w.DISALLOWED, drain_disallowed())


class Lifecycle(WorkerCase):
    def test_sigterm_mid_job(self):                                            # F3
        self.scenario(claude_sleep=60)
        self.server.add_job()
        p = subprocess.Popen([sys.executable, WORKER], env=self.env(), cwd=self.tmp.name,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        marker = os.path.join(self.stubs, 'claude.marker')
        for _ in range(200):
            if os.path.exists(marker) and os.path.getsize(marker):
                break
            time.sleep(0.05)
        self.assertEqual(self.job_dirs(), ['7'])
        time.sleep(0.2)
        p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=15)
        self.assert_clean_log(out + err)
        self.assertEqual(p.returncode, 128 + signal.SIGTERM)
        self.assertEqual(self.job_dirs(), [])
        self.assertFalse(alive(self.claude_call()['pid']))
        self.assertEqual(self.server.reports(), [])     # the lease expires server-side

    def test_lock_held_exits_immediately(self):                                # F9
        os.makedirs(self.work, exist_ok=True)
        with open(os.path.join(self.work, '.lock'), 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.server.add_job()
            t0 = time.time()
            p = self.run_worker()
            self.assertLess(time.time() - t0, 5)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(self.server.requests, [])

    def test_server_unreachable(self):                                         # F10
        self.write_env(f'http://127.0.0.1:{closed_port()}')
        p = self.run_worker()
        self.assertEqual(p.returncode, 0)
        self.assertEqual(len(p.stderr.splitlines()), 1, p.stderr)
        self.assertIn('unreachable', p.stderr)
        p = self.run_worker()                    # once per outage, not once a minute
        self.assertEqual(p.stderr, '')
        self.write_env(self.server.url)
        p = self.run_worker()
        self.assertIn('reachable again', p.stderr)

    def test_complete_5xx_keeps_result(self):                                  # F11
        self.server.status['complete'] = [503]
        self.server.add_job()
        self.run_worker()
        self.assertEqual(self.job_dirs(), ['7'])
        d = os.path.join(self.work, '7')
        self.assertEqual(os.listdir(d), ['result.json'])   # bundle, subs, raw output gone
        first = self.server.reports('complete')[0][1]

        self.server.requests.clear()
        self.run_worker()
        reps = self.server.reports()
        self.assertEqual(len(reps), 1)
        self.assertEqual(reps[0][0], '/worker/jobs/7/complete')
        self.assertEqual(reps[0][1], first)               # same lease, same summary
        self.assertEqual(self.job_dirs(), [])

    def test_unreachable_on_complete_keeps_result_and_stops(self):
        self.server.add_job(7)
        self.server.add_job(8)
        self.server.status['complete'] = [502]
        self.run_worker()
        self.assertEqual(self.job_dirs(), ['7'])
        self.assertEqual(len(self.server.claims()), 1)   # no second claim while it's sick

    def test_fail_report_kept_too(self):
        self.scenario(info=dict(INFO, duration=999 * 60))
        self.server.status['fail'] = [500]
        self.server.add_job()
        self.run_worker()
        self.assertEqual(self.job_dirs(), ['7'])
        self.run_worker()
        self.assertEqual([b['error_code'] for _, b in self.server.reports('fail')],
                         ['too_long', 'too_long'])
        self.assertEqual(self.job_dirs(), [])

    def test_stale_saved_result_dropped(self):
        d = os.path.join(self.work, '9')
        os.makedirs(d)
        p = os.path.join(d, 'result.json')
        with open(p, 'w') as f:
            json.dump({'kind': 'complete', 'body': {'lease_id': 'x', 'md': SUMMARY}}, f)
        old = time.time() - 2 * 24 * 3600
        os.utime(p, (old, old))
        self.run_worker()
        self.assertEqual(self.server.reports(), [])
        self.assertEqual(self.job_dirs(), [])

    def test_crash_leftovers_swept(self):
        os.makedirs(os.path.join(self.work, '5'))
        open(os.path.join(self.work, '5', 'bundle.txt'), 'w').close()
        self.run_worker()
        self.assertEqual(self.job_dirs(), [])

    def test_env_file_must_be_private(self):
        self.write_env(self.server.url, mode=0o644)
        p = self.run_worker()
        self.assertEqual(p.returncode, 1)
        self.assertIn('chmod 600', p.stderr)
        self.assertEqual(self.server.requests, [])

    def test_plain_http_only_for_localhost(self):
        self.write_env('http://example.org')
        p = self.run_worker()
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.server.requests, [])

    def test_bad_token_logged(self):
        with open(self.env_file, 'w') as f:
            f.write(f'WORKER_TOKEN=wrong\nSERVER_URL={self.server.url}\n')
        p = self.run_worker()
        self.assertIn('401', p.stderr)


class RepoHygiene(WorkerCase):
    def test_git_status_unchanged(self):                                       # F14
        """Uses the real .work/ in the repo, as the LaunchAgent does."""
        lock = os.path.join(ROOT, '.work', '.lock')
        if os.path.exists(lock):
            with open(lock, 'w') as f:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    self.skipTest('a real worker run holds the lock')
        before = git_status()
        self.server.add_job(424242)
        env = self.env()
        del env['WORKER_WORK_DIR']
        p = subprocess.run([sys.executable, WORKER], env=env, capture_output=True, text=True,
                           timeout=60)
        self.assert_clean_log(p.stderr)
        self.assertTrue(self.server.reports()[0][0].endswith('/complete'))
        self.assertEqual(git_status(), before)
        self.assertFalse(os.path.exists(os.path.join(ROOT, '.work', '424242')))

    def test_log_is_content_free_across_outcomes(self):                        # F15
        """Every run above goes through assert_clean_log; this one also reads a log file
        the way launchd writes it."""
        log = os.path.join(self.tmp.name, 'worker.log')
        for sc in ({}, {'claude': 'is_error'}, {'meta_error': 'Private video'},
                   {'info': dict(INFO, duration=10 ** 6)}):
            self.scenario(**sc)
            self.server.add_job()
            with open(log, 'a') as f:
                subprocess.run([sys.executable, WORKER], env=self.env(), stdout=f, stderr=f,
                               timeout=60)
        with open(log) as f:
            text = f.read()
        self.assertIn('job 7', text)
        self.assert_clean_log(text)


class Plist(unittest.TestCase):
    def test_template_renders_and_lints(self):
        if sys.platform != 'darwin':
            self.skipTest('plutil is macOS-only')
        out = subprocess.run([os.path.join(ROOT, 'ops', 'render-worker-plist')],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn('@', re.sub(r'<!--.*?-->', '', out.stdout, flags=re.S))
        self.assertIn('<string>com.ahdimel.smartytconsumer.worker</string>', out.stdout)
        with open(os.path.join(ROOT, 'ops', 'worker.plist.template')) as f:
            self.assertNotIn('.nvm/', f.read())
        with tempfile.NamedTemporaryFile('w', suffix='.plist') as f:
            f.write(out.stdout)
            f.flush()
            lint = subprocess.run(['plutil', '-lint', f.name], capture_output=True, text=True)
        self.assertEqual(lint.returncode, 0, lint.stdout)


def drain_disallowed():
    with open(os.path.join(ROOT, 'drain')) as f:
        return re.search(r'--disallowed-tools "([^"]+)"', f.read()).group(1)


def git_status():
    return subprocess.run(['git', '-C', ROOT, 'status', '--porcelain'], capture_output=True,
                          text=True).stdout


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # a zombie still answers kill(0); ask ps for the real state
    st = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True)
    return bool(st.stdout.strip()) and not st.stdout.strip().startswith('Z')


def closed_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


if __name__ == '__main__':
    unittest.main()
