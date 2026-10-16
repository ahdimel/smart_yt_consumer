"""Owner's command line, for what the admin page can't do: the first admin, and getting back in.

  python -m server.cli invite --name Ahdi --email hello@ahdimel.com --admin
  python -m server.cli reissue --email hello@ahdimel.com      # lost or leaked admin link

Each prints an invite link once. Reads DB_PATH and PUBLIC_ORIGIN like the app.
"""
import argparse
import time
from contextlib import closing

from . import db, users
from .config import Settings


def main(argv=None):
    p = argparse.ArgumentParser(prog='python -m server.cli')
    sub = p.add_subparsers(dest='cmd', required=True)
    inv = sub.add_parser('invite', help='create a user and print their invite link')
    inv.add_argument('--name', required=True)
    inv.add_argument('--email', required=True)
    inv.add_argument('--admin', action='store_true')
    re_ = sub.add_parser('reissue', help="replace a user's link (the old one stops working)")
    re_.add_argument('--email', required=True)
    args = p.parse_args(argv)

    s = Settings.from_env()
    db.init(s.db_path)
    with closing(db.connect(s.db_path)) as conn:
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
