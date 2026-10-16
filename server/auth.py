"""Invite tokens, the token-miss rate limiter, and the cross-origin check (proposal §8)."""
import hashlib
import hmac
import secrets
import threading
from collections import defaultdict, deque
from urllib.parse import urlsplit

COOKIE = 'session'
COOKIE_MAX_AGE = 365 * 24 * 3600


def new_token():
    return secrets.token_urlsafe(32)          # 256 bits


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def find_user(conn, token):
    """The user row for a token, revoked or not; None when unknown.

    Lookup is by hash, so comparison time says nothing about how close a guess was.
    """
    if not token or len(token) > 128:
        return None
    return conn.execute('SELECT * FROM users WHERE token_hash = ?', (hash_token(token),)).fetchone()


def worker_ok(configured, presented):
    if not configured or not presented:
        return False
    return hmac.compare_digest(hash_token(configured), hash_token(presented))


def bearer(request):
    """The bearer token, '' for a malformed Authorization header, None when there is none."""
    h = request.headers.get('authorization')
    if h is None:
        return None
    scheme, _, value = h.partition(' ')
    return value.strip() if scheme.lower() == 'bearer' else ''


class MissLimiter:
    """After `limit` unknown tokens from one IP within `window` seconds, refuse that IP's
    token lookups (valid or not) until the window rolls. In memory: one instance, ≤10 users."""

    def __init__(self, clock, limit=10, window=600):
        self.clock, self.limit, self.window = clock, limit, window
        self.misses = defaultdict(deque)
        self.lock = threading.Lock()

    def _trim(self, ip):
        q, floor = self.misses[ip], self.clock() - self.window
        while q and q[0] <= floor:
            q.popleft()
        return q

    def blocked(self, ip):
        with self.lock:
            return len(self._trim(ip)) >= self.limit

    def miss(self, ip):
        with self.lock:
            self._trim(ip).append(self.clock())


def client_ip(request, header=None):
    if header:
        v = request.headers.get(header)
        if v:
            return v.split(',')[-1].strip()
    return request.client.host if request.client else 'unknown'


def own_origin(request, public_origin=None):
    if public_origin:
        return public_origin
    return f'{request.url.scheme}://{request.headers.get("host", "")}'


def same_origin(request, public_origin=None):
    """True unless the request carries evidence of coming from another site.

    Browsers send Origin on every cross-origin POST, and Sec-Fetch-Site where supported. A
    request with neither is not from a browser page, so it carries no ambient cookie risk.

    Every page sends Referrer-Policy: no-referrer, under which browsers send `Origin: null` on
    their own same-origin form POSTs (Fetch standard, "serialize a request origin"). So when
    the browser vouches with Sec-Fetch-Site: same-origin, a null Origin is not evidence of
    anything. Without Sec-Fetch-Site, a null Origin (sandboxed iframes, data: pages) is refused.
    """
    site = request.headers.get('sec-fetch-site')
    if site is not None and site not in ('same-origin', 'none'):
        return False
    origin = request.headers.get('origin')
    if origin is None:
        return True
    if origin == 'null':
        return site is not None
    want = urlsplit(own_origin(request, public_origin))
    got = urlsplit(origin)
    return (got.scheme, got.netloc.lower()) == (want.scheme, want.netloc.lower())
