"""Runtime settings, read from the environment. The secrets are WORKER_TOKEN and RESEND_API_KEY,
kept out of repr() so a stray log line or traceback can't print them."""
import os
from dataclasses import dataclass, field

DAY = 24 * 3600
WEEK = 7 * DAY
RETENTION = 30 * DAY          # D2: summaries, the cache and job↔video links


@dataclass(frozen=True)
class Settings:
    # Outside the repo by default: friend data never sits in the working tree (D7).
    db_path: str = os.path.expanduser('~/.local/share/smart_yt_consumer/server.db')
    worker_token: str | None = field(default=None, repr=False)
    # e.g. https://desloppify.ahdimel.com. Used for invite links and the Origin check; when
    # unset, the request's own scheme and Host stand in (local development).
    public_origin: str | None = None
    cookie_secure: bool = True
    # Behind Railway's edge, request.client is the proxy. Name the header the edge sets
    # (e.g. X-Real-IP) to rate-limit by the real client; leave unset when not behind a proxy,
    # because a client can send any header it likes.
    client_ip_header: str | None = None
    lease_seconds: int = 30 * 60
    # Email (§5.1, D9). No key means no mailer: finished jobs wait at email_status='pending'.
    resend_api_key: str | None = field(default=None, repr=False)
    resend_api_url: str = 'https://api.resend.com'
    mail_from: str = 'desloppify <desloppify@notify.ahdimel.com>'
    mail_reply_to: str = 'hello@ahdimel.com'

    @classmethod
    def from_env(cls):
        env = os.environ
        kw = {}
        if env.get('DB_PATH'):
            kw['db_path'] = env['DB_PATH']
        if env.get('WORKER_TOKEN'):
            kw['worker_token'] = env['WORKER_TOKEN']
        if env.get('PUBLIC_ORIGIN'):
            kw['public_origin'] = env['PUBLIC_ORIGIN'].rstrip('/')
        if env.get('COOKIE_SECURE'):
            kw['cookie_secure'] = env['COOKIE_SECURE'] not in ('0', 'false', 'no')
        if env.get('CLIENT_IP_HEADER'):
            kw['client_ip_header'] = env['CLIENT_IP_HEADER']
        if env.get('LEASE_SECONDS'):
            kw['lease_seconds'] = int(env['LEASE_SECONDS'])
        for key in ('RESEND_API_KEY', 'RESEND_API_URL', 'MAIL_FROM', 'MAIL_REPLY_TO'):
            if env.get(key):
                kw[key.lower()] = env[key]
        return cls(**kw)
