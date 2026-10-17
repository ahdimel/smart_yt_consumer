"""Owner's command line, for what the admin page can't do: the first admin, and getting back in.

  python -m server.cli invite --name Ahdi --email hello@ahdimel.com --admin
  python -m server.cli reissue --email hello@ahdimel.com      # lost or leaked admin link
  python -m server.cli test-email --to someone@gmail.com       # deliverability check (§10.2 step 6)
  python -m server.cli purge [--vacuum]                        # one retention pass now; prints counts

invite and reissue print an invite link once. Reads DB_PATH, PUBLIC_ORIGIN and the mail
settings like the app. On Railway, run these in the service with `railway ssh` (ops.local.txt §2).
"""
import argparse
import time
from contextlib import closing

from . import db, mail, retention, users
from .config import Settings


def test_email(s, to):
    mailer = mail.from_settings(s)
    if mailer is None:
        return 'RESEND_API_KEY is not set'
    origin = s.public_origin or 'http://localhost:8000'
    text = (f'A test email from {origin}.\n\nIf this is in your inbox, sending works. Reply to it '
            'to check that replies reach hello@ahdimel.com.\n')
    body = mail._html(f'A test email from <a href="{origin}">{origin}</a>.',
                      'If this is in your inbox, sending works. Reply to it to check that '
                      'replies reach hello@ahdimel.com.')
    outcome = mailer.send(to, 'Test email', body, text, key=f'test-{time.time_ns()}')
    print(f'{outcome} (HTTP {mailer.last_status})')
    return None if outcome == 'sent' else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog='python -m server.cli')
    sub = p.add_subparsers(dest='cmd', required=True)
    inv = sub.add_parser('invite', help='create a user and print their invite link')
    inv.add_argument('--name', required=True)
    inv.add_argument('--email', required=True)
    inv.add_argument('--admin', action='store_true')
    re_ = sub.add_parser('reissue', help="replace a user's link (the old one stops working)")
    re_.add_argument('--email', required=True)
    te = sub.add_parser('test-email', help='send one test email through the configured mailer')
    te.add_argument('--to', required=True)
    pu = sub.add_parser('purge', help='run the retention purge once and print what it removed')
    pu.add_argument('--vacuum', action='store_true',
                    help='then rewrite the file, dropping free pages written before secure_delete')
    args = p.parse_args(argv)

    s = Settings.from_env()
    if args.cmd == 'test-email':
        return test_email(s, args.to)
    db.init(s.db_path)
    with closing(db.connect(s.db_path)) as conn:
        if args.cmd == 'purge':
            n, m = retention.purge(conn, int(time.time()))
            print(f'purged summaries={n} jobs={m}')
            if args.vacuum:
                before = conn.execute('PRAGMA freelist_count').fetchone()[0]
                conn.execute('VACUUM')
                conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                print(f'vacuumed free_pages={before}')
            return None
        if args.cmd == 'invite':
            _, token = users.create(conn, args.name, args.email, int(time.time()), args.admin)
        else:
            rows = conn.execute('SELECT id FROM users WHERE email = ?', (args.email,)).fetchall()
            if len(rows) != 1:
                return f'{len(rows)} users have that email; expected exactly 1'
            token = users.reissue(conn, rows[0]['id'])
    print(users.invite_link(s.public_origin or 'http://localhost:8000', token))


if __name__ == '__main__':
    raise SystemExit(main())
