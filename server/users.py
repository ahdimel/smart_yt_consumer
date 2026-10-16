"""Creating, revoking and re-keying users. The raw token is returned once and never stored."""
from . import auth


def create(conn, name, email, now, is_admin=False):
    token = auth.new_token()
    uid = conn.execute(
        'INSERT INTO users (name, email, token_hash, is_admin, created_at) VALUES (?, ?, ?, ?, ?)',
        (name, email, auth.hash_token(token), int(is_admin), now)).lastrowid
    return uid, token


def reissue(conn, uid):
    """A fresh link for a user whose old one leaked: the old token stops working, history stays."""
    token = auth.new_token()
    n = conn.execute('UPDATE users SET token_hash = ?, revoked_at = NULL WHERE id = ?',
                     (auth.hash_token(token), uid)).rowcount
    return token if n else None


def revoke(conn, uid, now):
    conn.execute('UPDATE users SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL', (now, uid))


def invite_link(origin, token):
    return f'{origin}/u/{token}'
