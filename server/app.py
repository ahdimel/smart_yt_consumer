"""HTTP layer: routes, credentials, security headers. The rules live in intake, protocol, admin.

Run locally:  server/.venv/bin/uvicorn server.app:create_app --factory --no-access-log
(--no-access-log matters: access lines carry paths, and /u/<token> is a path.)

Each route accepts exactly one kind of credential (§8):
  user cookie       /, /welcome, /about, and /api/requests without an Authorization header
  user bearer       /api/requests with an Authorization header (iOS Shortcut)
  admin cookie      /admin*
  worker bearer     /worker/*
  capability        /s/<public_id>: the unguessable ID is the credential (D3)
"""
import asyncio
import json
import logging
import sys
import time
from contextlib import asynccontextmanager, closing
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from . import admin, auth, codes, db, intake, mail, pages, protocol, render, urls, users
from .config import RETENTION, Settings

log = logging.getLogger('server')

CSP = ("default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; "
       "frame-ancestors 'none'; form-action 'self'")
INTAKE_LIMIT = 2 * 1024
COMPLETE_LIMIT = 1024 * 1024
SMALL_LIMIT = 16 * 1024
STATIC = Path(__file__).with_name('static')
STATIC_TYPES = {'app.css': 'text/css', 'summary.css': 'text/css',
                'summary.js': 'text/javascript'}
# What a browser form submission shows on the home page, keyed by the ?m= code.
MESSAGES = {
    'queued': 'Queued. You’ll get an email when it’s ready.',
    'done': 'Done. The email is on its way.',
    'invalid_url': codes.INVALID_URL_MESSAGE,
    'several_videos': codes.SEVERAL_VIDEOS_MESSAGE,
    'quota_daily': "You've used all of today's requests.",
    'quota_weekly': "You've used all of this week's requests.",
    'busy': 'The summarizer is at its daily limit. Try again later.',
    'paused': 'Summaries are paused for now. Try again later.',
}
ERRORS = {400: 'bad_request', 401: 'unauthorized', 403: 'forbidden', 405: 'method_not_allowed',
          409: 'conflict', 413: 'too_large', 415: 'unsupported_media_type', 422: 'invalid',
          429: 'too_many_attempts'}


def err(status, code, message=None, **extra):
    body = {'error': code, **({'message': message} if message else {}), **extra}
    return JSONResponse(body, status)


async def read_body(request, limit):
    n = request.headers.get('content-length')
    if n and n.isdigit() and int(n) > limit:
        raise HTTPException(413)
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > limit:
            raise HTTPException(413)
    return bytes(data)


def form(raw):
    return {k: v[0] for k, v in parse_qs(raw.decode('utf-8', 'replace')).items()}


def json_object(raw):
    try:
        obj = json.loads(raw or b'{}')
    except ValueError:
        raise HTTPException(400)
    if not isinstance(obj, dict):
        raise HTTPException(400)
    return obj


def submitted_text(request, raw):
    """Whatever the friend sent, as one string for urls.video_id()."""
    ctype = request.headers.get('content-type', '').split(';')[0].strip().lower()
    if ctype == 'application/json':
        obj = json_object(raw)
        parts = [obj.get('url'), obj.get('text')]
    elif ctype == 'application/x-www-form-urlencoded':
        f = form(raw)
        parts = [f.get('url'), f.get('text')]
    elif ctype in ('text/plain', ''):
        parts = [raw.decode('utf-8', 'replace')]
    else:
        raise HTTPException(415)
    return ' '.join(p for p in parts if isinstance(p, str))


def job_view(job):
    view = {'id': job['public_id'], 'status': job['status'], 'created_at': job['created_at']}
    if job['status'] == 'done':
        view['summary_url'] = f'/s/{job["public_id"]}'
    if job['status'] == 'failed':
        view['error'] = job['error_code']
        view['message'] = codes.CODES[job['error_code']].message
    return view


def create_app(settings=None, clock=None, mailer=None):
    """`mailer` defaults to Resend when RESEND_API_KEY is set, else none (mail waits)."""
    if not log.handlers:
        # Job IDs, user IDs and codes only; never a URL, video ID, title or token.
        h = logging.StreamHandler(sys.stdout)       # Railway shows stderr as errors
        h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    settings = settings or Settings.from_env()
    clock = clock or (lambda: int(time.time()))
    mailer = mailer if mailer is not None else mail.from_settings(settings)
    db.init(settings.db_path)
    limiter = auth.MissLimiter(clock)

    def connect():
        return closing(db.connect(settings.db_path))

    def deliver(origin_):
        """Send whatever email is due. Runs after a response, and from the loop below."""
        with connect() as conn:
            mail.deliver_pending(conn, mailer, origin_, clock())

    async def mail_loop():
        # Retries with backoff, and stale `sending` rows; the first attempt is made right after
        # the request that finished the job. Origin: PUBLIC_ORIGIN, as there is no request here.
        while True:
            await asyncio.sleep(mail.LOOP_SECONDS)
            try:
                await run_in_threadpool(deliver, settings.public_origin or '')
            except Exception as e:
                log.warning('mail loop error=%s', type(e).__name__)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(mail_loop()) if mailer is not None else None
        log.info('started mailer=%s', 'resend' if mailer is not None else 'none')
        yield
        if task:
            task.cancel()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings, app.state.clock, app.state.limiter = settings, clock, limiter
    app.state.mailer = mailer

    async def in_db(fn, *args):
        def call():
            with connect() as conn:
                return fn(conn, *args)
        return await run_in_threadpool(call)

    def origin(request):
        return auth.own_origin(request, settings.public_origin)

    def then_mail(resp, request):
        if mailer is not None:
            resp.background = BackgroundTask(deliver, origin(request))
        return resp

    def lookup(conn, request, token):
        """Active user for a token, or None. Unknown tokens count against the caller's IP."""
        ip = auth.client_ip(request, settings.client_ip_header)
        if limiter.blocked(ip):
            raise HTTPException(429)
        user = auth.find_user(conn, token)
        if user is None:
            limiter.miss(ip)
            return None
        if user['revoked_at'] is not None:
            return None
        conn.execute('UPDATE users SET last_seen_at = ? WHERE id = ?', (clock(), user['id']))
        return user

    def cookie_user(conn, request):
        token = request.cookies.get(auth.COOKIE)
        return lookup(conn, request, token) if token else None

    def private(request):
        resp = HTMLResponse(pages.bare(pages.PRIVATE))
        if auth.COOKIE in request.cookies:
            resp.delete_cookie(auth.COOKIE, path='/')
        return resp

    def admin_user(conn, request):
        if 'authorization' in request.headers:
            raise HTTPException(401)
        user = cookie_user(conn, request)
        if user is None or not user['is_admin']:
            raise HTTPException(404)
        return user

    # ── middleware and errors ─────────────────────────────────────────────

    @app.middleware('http')
    async def security_headers(request, call_next):
        resp = await call_next(request)
        h = resp.headers
        h['Content-Security-Policy'] = CSP
        h['Referrer-Policy'] = 'no-referrer'
        h['X-Robots-Tag'] = 'noindex'
        h['X-Content-Type-Options'] = 'nosniff'
        if not request.url.path.startswith('/static/'):
            h['Cache-Control'] = 'no-store'
        return resp

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if exc.status_code == 404:
            return HTMLResponse(pages.bare(pages.NOT_FOUND), 404)
        return err(exc.status_code, ERRORS.get(exc.status_code, 'error'))

    # ── public ────────────────────────────────────────────────────────────

    @app.api_route('/healthz', methods=['GET', 'HEAD'])     # HEAD: curl -I, uptime checks
    def healthz():
        return {'ok': True}

    @app.get('/static/{name}')
    def static(name: str):
        if name not in STATIC_TYPES:
            raise HTTPException(404)
        return Response((STATIC / name).read_text(), media_type=STATIC_TYPES[name])

    @app.get('/s/{public_id}')
    def summary_page(public_id: str):
        """The summary. 404 for an ID that never existed or isn't done, 410 once expired."""
        if not 16 <= len(public_id) <= 64:
            raise HTTPException(404)
        now = clock()
        with connect() as conn:
            job = conn.execute('SELECT status, video_id, finished_at FROM jobs WHERE public_id = ?',
                               (public_id,)).fetchone()
            if job is None or job['status'] != 'done':
                raise HTTPException(404)
            s = conn.execute('SELECT md, expires_at FROM summaries WHERE video_id = ?',
                             (job['video_id'],)).fetchone() if job['video_id'] else None
        # The link lives as long as both the summary and the job's own 30 days (D2). A cache
        # entry refreshed by someone else's request doesn't revive an old link.
        until = min(s['expires_at'], job['finished_at'] + RETENTION) if s else 0
        if until <= now:
            return HTMLResponse(render.gone(), 410)
        return HTMLResponse(render.page(s['md'], job['video_id'], until))

    # ── friends ───────────────────────────────────────────────────────────

    @app.get('/u/{token}')
    def invite(token: str, request: Request):
        with connect() as conn:
            user = lookup(conn, request, token)
            if user is None:
                raise HTTPException(404)
        resp = RedirectResponse('/' if user['welcomed_at'] else '/welcome', 303)
        resp.set_cookie(auth.COOKIE, token, max_age=auth.COOKIE_MAX_AGE, path='/', httponly=True,
                        secure=settings.cookie_secure, samesite='lax')
        return resp

    @app.get('/')
    def home(request: Request, m: str | None = None):
        with connect() as conn:
            user = cookie_user(conn, request)
            if user is None:
                return private(request)
            now = clock()
            jobs = conn.execute(
                'SELECT status, created_at FROM jobs WHERE user_id = ? '
                'ORDER BY created_at DESC, id DESC LIMIT 20', (user['id'],)).fetchall()
            left = intake.remaining(conn, user, now)
        message = MESSAGES.get(m)
        return HTMLResponse(pages.home(user, jobs, *left, message=message))

    @app.get('/welcome')
    def welcome(request: Request):
        with connect() as conn:
            user = cookie_user(conn, request)
            if user is None:
                return private(request)
            conn.execute('UPDATE users SET welcomed_at = ? WHERE id = ? AND welcomed_at IS NULL',
                         (clock(), user['id']))
        return HTMLResponse(pages.placeholder('Welcome', 'The intro page arrives in M4.'))

    @app.get('/about')
    def about(request: Request):
        with connect() as conn:
            if cookie_user(conn, request) is None:
                return private(request)
        return HTMLResponse(pages.placeholder('About', 'The intro page arrives in M4.'))

    @app.post('/api/requests')
    async def submit(request: Request):
        token = auth.bearer(request)
        via_cookie = token is None
        if via_cookie:
            token = request.cookies.get(auth.COOKIE)
            if token and not auth.same_origin(request, settings.public_origin):
                return err(403, 'cross_origin')
        if not token:
            return err(401, 'unauthorized')
        raw = await read_body(request, INTAKE_LIMIT)
        text = submitted_text(request, raw)
        browser_form = via_cookie and request.headers.get('content-type', '').startswith(
            'application/x-www-form-urlencoded')

        def work(conn):
            user = lookup(conn, request, token)
            if user is None:
                return err(401, 'unauthorized')
            try:
                vid = urls.video_id(text)
            except urls.InvalidURL as e:
                code = 'several_videos' if e.reason == 'several_videos' else 'invalid_url'
                return err(400, 'invalid_url', MESSAGES[code], reason=code)
            try:
                job, created = intake.submit(conn, user, vid, clock())
            except intake.Rejected as r:
                extra = {'retry_at': r.retry_at} if r.retry_at else {}
                return err(r.status, r.code, r.message, **extra)
            log.info('submit job=%s user=%s status=%s', job['id'], user['id'], job['status'])
            return JSONResponse(job_view(job),
                                202 if created and job['status'] != 'done' else 200)

        resp = await in_db(work)
        if not browser_form:
            return then_mail(resp, request) if resp.status_code in (200, 202) else resp
        if resp.status_code in (200, 202):
            status = json.loads(resp.body)['status']
            return then_mail(RedirectResponse(
                f'/?m={"done" if status == "done" else "queued"}', 303), request)
        body = json.loads(resp.body)
        code = body.get('reason') or body['error']
        if resp.status_code == 401:
            return resp
        return RedirectResponse(f'/?m={code}', 303)

    # ── worker ────────────────────────────────────────────────────────────

    def worker_only(request):
        if not auth.worker_ok(settings.worker_token, auth.bearer(request)):
            raise HTTPException(401)

    @app.post('/worker/claim')
    async def worker_claim(request: Request):
        worker_only(request)
        body = json_object(await read_body(request, SMALL_LIMIT))
        version = body.get('version')
        version = version if isinstance(version, str) and len(version) <= 64 else None
        job = await in_db(lambda conn: protocol.claim(conn, clock(), settings.lease_seconds, version))
        if job is None:
            return Response(status_code=204)
        log.info('claim job=%s attempt=%s', job['job_id'], job['attempt'])
        return JSONResponse(job)

    async def report(request, job_id, limit, fn, what):
        worker_only(request)
        body = json_object(await read_body(request, limit))

        try:
            await in_db(fn, job_id, body, clock())
        except protocol.ProtocolError as e:
            log.info('%s job=%s rejected=%s', what, job_id, e.code)
            return err(e.status, e.code)
        log.info('%s job=%s', what, job_id)
        return then_mail(JSONResponse({'ok': True}), request)

    @app.post('/worker/jobs/{job_id}/complete')
    async def worker_complete(job_id: int, request: Request):
        return await report(request, job_id, COMPLETE_LIMIT, protocol.complete, 'complete')

    @app.post('/worker/jobs/{job_id}/fail')
    async def worker_fail(job_id: int, request: Request):
        return await report(request, job_id, SMALL_LIMIT, protocol.fail, 'fail')

    # ── admin ─────────────────────────────────────────────────────────────

    @app.get('/admin')
    def admin_page(request: Request):
        with connect() as conn:
            me = admin_user(conn, request)
            return HTMLResponse(admin.page(admin.usage(conn, clock()), me['id']))

    @app.get('/admin/usage.json')
    def admin_json(request: Request):
        with connect() as conn:
            admin_user(conn, request)
            return JSONResponse(admin.usage(conn, clock()))

    async def admin_post(request, fn):
        """Admin check first (404 to anyone else), then the Origin check, then the action."""
        def gate(conn):
            return admin_user(conn, request)
        me = await in_db(gate)
        if not auth.same_origin(request, settings.public_origin):
            return err(403, 'cross_origin')
        fields = form(await read_body(request, SMALL_LIMIT))
        return await in_db(lambda conn: fn(conn, me, fields))

    def back():
        return RedirectResponse('/admin', 303)

    def number(fields, key, lo, hi, blank=False):
        v = fields.get(key, '').strip()
        if blank and v == '':
            return None
        if not v.isdigit() or not lo <= int(v) <= hi:
            raise HTTPException(400)
        return int(v)

    @app.post('/admin/invites')
    async def admin_invite(request: Request):
        def act(conn, me, f):
            name, email = f.get('name', '').strip(), f.get('email', '').strip()
            if not (0 < len(name) <= 100 and 0 < len(email) <= 200 and '@' in email):
                raise HTTPException(400)
            uid, token = users.create(conn, name, email, clock())
            log.info('invite user=%s', uid)
            return HTMLResponse(admin.invite_page(name, users.invite_link(origin(request), token)))
        return await admin_post(request, act)

    @app.post('/admin/users/{uid}/revoke')
    async def admin_revoke(uid: int, request: Request):
        def act(conn, me, f):
            if uid == me['id']:
                raise HTTPException(400)
            users.revoke(conn, uid, clock())
            log.info('revoke user=%s', uid)
            return back()
        return await admin_post(request, act)

    @app.post('/admin/users/{uid}/reissue')
    async def admin_reissue(uid: int, request: Request):
        def act(conn, me, f):
            token = users.reissue(conn, uid)
            if token is None:
                raise HTTPException(404)
            log.info('reissue user=%s', uid)
            name = conn.execute('SELECT name FROM users WHERE id = ?', (uid,)).fetchone()['name']
            return HTMLResponse(admin.invite_page(name, users.invite_link(origin(request), token)))
        return await admin_post(request, act)

    @app.post('/admin/users/{uid}/limits')
    async def admin_limits(uid: int, request: Request):
        def act(conn, me, f):
            conn.execute(
                'UPDATE users SET daily_limit = ?, weekly_limit = ?, max_minutes = ? WHERE id = ?',
                (number(f, 'daily_limit', 0, 1000), number(f, 'weekly_limit', 0, 5000),
                 number(f, 'max_minutes', 1, 24 * 60), uid))
            return back()
        return await admin_post(request, act)

    @app.post('/admin/pause')
    async def admin_pause(request: Request):
        def act(conn, me, f):
            conn.execute('UPDATE settings SET paused = 1 WHERE id = 1')
            log.info('paused')
            return back()
        return await admin_post(request, act)

    @app.post('/admin/resume')
    async def admin_resume(request: Request):
        def act(conn, me, f):
            conn.execute('UPDATE settings SET paused = 0 WHERE id = 1')
            log.info('resumed')
            return back()
        return await admin_post(request, act)

    @app.post('/admin/settings')
    async def admin_settings(request: Request):
        def act(conn, me, f):
            conn.execute(
                'UPDATE settings SET global_daily_limit = ?, global_daily_token_ceiling = ? WHERE id = 1',
                (number(f, 'global_daily_limit', 0, 10000),
                 number(f, 'global_daily_token_ceiling', 0, 10**12, blank=True)))
            return back()
        return await admin_post(request, act)

    return app
