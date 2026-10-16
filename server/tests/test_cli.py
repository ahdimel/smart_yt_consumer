"""The owner's CLI: first admin, and recovery when the admin link is lost."""
from server import cli

from .conftest import Env


def test_invite_then_reissue(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'cli.db'
    monkeypatch.setenv('DB_PATH', str(path))
    monkeypatch.setenv('PUBLIC_ORIGIN', 'https://testserver')
    assert cli.main(['invite', '--name', 'Owner', '--email', 'o@example.org', '--admin']) is None
    first = capsys.readouterr().out.strip()
    assert cli.main(['reissue', '--email', 'o@example.org']) is None
    second = capsys.readouterr().out.strip()
    assert first.startswith('https://testserver/u/') and second != first
    assert 'expected exactly 1' in cli.main(['reissue', '--email', 'nobody@example.org'])

    env = Env(path)
    old, new = first.rsplit('/', 1)[1], second.rsplit('/', 1)[1]
    assert env.client.get(f'/u/{old}', follow_redirects=False).status_code == 404
    assert env.client.get(f'/u/{new}', follow_redirects=False).status_code == 303
    assert env.client.get('/admin', headers={'Cookie': f'session={new}'}).status_code == 200
