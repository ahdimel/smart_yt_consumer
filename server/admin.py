"""The owner's view: usage, not content (proposal §6, §11 G).

Queries here select explicit non-content columns from `jobs` and never touch `summaries`, so
no URL, video ID, title, verdict or summary text can reach an admin response. `public_id` is
excluded too: it is the capability URL to a friend's summary.
"""
from collections import Counter
from html import escape

from . import db, protocol
from .config import DAY, WEEK
from .pages import layout, ts

JOB_COLS = ('id, user_id, status, cache_hit, coalesced_with, attempts, error_code, input_tokens, '
            'cache_write_tokens, cache_read_tokens, output_tokens, cost_usd, model, '
            'email_status, created_at, finished_at')
TOKENS = ('input_tokens', 'cache_write_tokens', 'cache_read_tokens', 'output_tokens')
WINDOWS = (('24h', DAY), ('7d', WEEK), ('all', None))


def _bucket(jobs):
    return {
        'requests': len(jobs),
        'cache_hits': sum(j['cache_hit'] for j in jobs),
        'coalesced': sum(j['coalesced_with'] is not None for j in jobs),
        'failed': sum(j['status'] == 'failed' for j in jobs),
        'tokens': {k: sum(j[k] for j in jobs) for k in TOKENS},
        'cost_usd_api_equivalent': round(sum(j['cost_usd'] for j in jobs), 4),
    }


def usage(conn, now):
    jobs = conn.execute(f'SELECT {JOB_COLS} FROM jobs ORDER BY created_at DESC, id DESC').fetchall()
    by_user = {}
    for j in jobs:
        by_user.setdefault(j['user_id'], []).append(j)

    users = []
    for u in conn.execute('SELECT * FROM users ORDER BY created_at, id'):
        mine = by_user.get(u['id'], [])
        users.append({
            'id': u['id'],
            'name': u['name'],
            'email': u['email'],
            'token_prefix': u['token_hash'][:8],
            'is_admin': bool(u['is_admin']),
            'revoked': u['revoked_at'] is not None,
            'created_at': u['created_at'],
            'last_seen_at': u['last_seen_at'],
            'limits': {'daily': u['daily_limit'], 'weekly': u['weekly_limit'],
                       'max_minutes': u['max_minutes']},
            'windows': {name: _bucket([j for j in mine if w is None or j['created_at'] > now - w])
                        for name, w in WINDOWS},
            'failures_by_code': dict(Counter(j['error_code'] for j in mine if j['status'] == 'failed')),
        })

    s = db.settings(conn)
    w = conn.execute('SELECT * FROM worker WHERE id = 1').fetchone()
    return {
        'now': now,
        'settings': {'paused': bool(s['paused']), 'global_daily_limit': s['global_daily_limit'],
                     'global_daily_token_ceiling': s['global_daily_token_ceiling']},
        'worker': {'last_seen': w['last_seen'], 'version': w['version']},
        'tokens_last_24h': protocol.tokens_last_day(conn, now),
        'queue_depth': sum(j['status'] in ('queued', 'running') for j in jobs),
        'emails_failed': sum(j['email_status'] == 'failed' for j in jobs),
        'emails_pending': sum(j['email_status'] in ('pending', 'sending') for j in jobs),
        'users': users,
        'requests': [{
            'id': j['id'], 'user_id': j['user_id'], 'created_at': j['created_at'],
            'finished_at': j['finished_at'], 'status': j['status'], 'error_code': j['error_code'],
            'cache_hit': bool(j['cache_hit']), 'coalesced': j['coalesced_with'] is not None,
            'attempts': j['attempts'], 'tokens': {k: j[k] for k in TOKENS},
            'cost_usd_api_equivalent': round(j['cost_usd'], 4), 'model': j['model'],
            'email_status': j['email_status'],
        } for j in jobs[:100]],
    }


def _n(v):
    return f'{v:,}'


def page(data, me_id):
    s = data['settings']
    names = {u['id']: u['name'] for u in data['users']}
    pause = ('<form method="post" action="/admin/resume"><button>Resume</button></form>'
             if s['paused'] else
             '<form method="post" action="/admin/pause"><button>Pause everything</button></form>')
    ceiling = s['global_daily_token_ceiling']

    user_rows = []
    for u in data['users']:
        w = {k: u['windows'][k] for k in ('24h', '7d', 'all')}
        t = w['all']['tokens']
        fails = ', '.join(f'{escape(c)}: {n}' for c, n in sorted(u['failures_by_code'].items())) or '—'
        lim = u['limits']
        actions = ''
        if not u['revoked'] and u['id'] != me_id:
            actions += (f'<form method="post" action="/admin/users/{u["id"]}/revoke">'
                        '<button>Revoke</button></form>')
        actions += (f'<form method="post" action="/admin/users/{u["id"]}/reissue">'
                    '<button>New link</button></form>')
        user_rows.append(f"""<tr>
<td>{escape(u['name'])}{' (admin)' if u['is_admin'] else ''}<br><small>{escape(u['email'])}</small>
  <br><small>token {escape(u['token_prefix'])}…{' · revoked' if u['revoked'] else ''}</small></td>
<td>{w['24h']['requests']} / {w['7d']['requests']} / {w['all']['requests']}</td>
<td>{_n(t['input_tokens'])} / {_n(t['cache_write_tokens'])} / {_n(t['cache_read_tokens'])} / {_n(t['output_tokens'])}</td>
<td>${w['all']['cost_usd_api_equivalent']:.2f}</td>
<td>{w['all']['cache_hits']}</td>
<td>{fails}</td>
<td>{ts(u['last_seen_at'])}</td>
<td><form method="post" action="/admin/users/{u['id']}/limits" class="limits">
  <input name="daily_limit" value="{lim['daily']}" size="3" aria-label="per day">
  <input name="weekly_limit" value="{lim['weekly']}" size="3" aria-label="per week">
  <input name="max_minutes" value="{lim['max_minutes']}" size="4" aria-label="max minutes">
  <button>Save</button></form></td>
<td>{actions}</td></tr>""")

    req_rows = ''.join(f"""<tr><td>{r['id']}</td><td>{escape(names.get(r['user_id'], '?'))}</td>
<td>{ts(r['created_at'])}</td><td>{r['status']}{' · cache' if r['cache_hit'] else ''}{' · coalesced' if r['coalesced'] else ''}</td>
<td>{escape(r['error_code'] or '')}</td><td>{r['attempts']}</td>
<td>{_n(r['tokens']['input_tokens'])} / {_n(r['tokens']['cache_write_tokens'])} / {_n(r['tokens']['cache_read_tokens'])} / {_n(r['tokens']['output_tokens'])}</td>
<td>${r['cost_usd_api_equivalent']:.2f}</td><td>{r['email_status'] or ''}</td></tr>"""
                       for r in data['requests'])

    return layout('Admin', f"""
<h1>Admin</h1>
<section class="row">
  <p>{'<strong>Paused.</strong>' if s['paused'] else 'Running.'}
     Worker last seen {ts(data['worker']['last_seen'])}{f" ({escape(data['worker']['version'])})" if data['worker']['version'] else ''}.
     Queue {data['queue_depth']}. Tokens, last 24h: {_n(data['tokens_last_24h'])}{f" of {_n(ceiling)}" if ceiling else ''}.
     Emails failed: {data['emails_failed']}, pending: {data['emails_pending']}.</p>
  {pause}
</section>
<form method="post" action="/admin/settings" class="row">
  <label>Global per day <input name="global_daily_limit" value="{s['global_daily_limit']}" size="4"></label>
  <label>Token ceiling per 24h <input name="global_daily_token_ceiling" value="{ceiling if ceiling is not None else ''}" size="10" placeholder="none"></label>
  <button>Save</button>
</form>

<h2>Users</h2>
<table>
<thead><tr><th>User</th><th>Requests 24h / 7d / all</th>
<th>Tokens in / cache-write / cache-read / out</th><th>Cost (API-equivalent)</th>
<th>Cache hits</th><th>Failures</th><th>Last seen</th><th>Limits day / week / min</th><th></th></tr></thead>
<tbody>{''.join(user_rows)}</tbody></table>

<h2>Invite</h2>
<form method="post" action="/admin/invites" class="row">
  <label>Name <input name="name" required></label>
  <label>Email <input name="email" type="email" required></label>
  <button>Create invite</button>
</form>

<h2>Recent requests</h2>
<p><small>Cost is an API-equivalent figure, not a charge.</small></p>
<table>
<thead><tr><th>#</th><th>User</th><th>Time</th><th>Status</th><th>Error</th><th>Attempts</th>
<th>Tokens in / cw / cr / out</th><th>Cost (API-eq.)</th><th>Email</th></tr></thead>
<tbody>{req_rows}</tbody></table>""")


def invite_page(name, link):
    return layout('Invite created', f"""
<h1>Invite for {escape(name)}</h1>
<p>Send this link to them. It is shown once and can't be retrieved later.</p>
<p><input readonly value="{escape(link)}" size="70" aria-label="invite link"></p>
<p><a href="/admin">Back to admin</a></p>""")
