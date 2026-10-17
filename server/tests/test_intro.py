"""§11 M5, M6: the intro page. M1–M4 (first visit, strangers) are in test_auth.py."""
import re

import pytest

from server import pages

ANDROID = ('Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) '
           'Chrome/131.0.0.0 Mobile Safari/537.36')
IPHONE = ('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 '
          '(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1')
MAC = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
       'Chrome/131.0.0.0 Safari/537.36')


def setup_blocks(html):
    """[(platform, open?)] in page order."""
    return [(m.group(1), m.group(2) == ' open')
            for m in re.finditer(r'<details class="setup" id="setup-(\w+)"( open)?>', html)]


@pytest.mark.parametrize('ua, mine', [(ANDROID, 'android'), (IPHONE, 'ios'), (MAC, 'desktop'),
                                      (None, 'desktop')])
def test_welcome_puts_the_visitors_platform_first(env, ua, mine):               # M5
    u = env.user(welcomed=False)
    headers = {**u.cookie, **({'User-Agent': ua} if ua else {})}
    page = env.client.get('/welcome', headers=headers).text
    blocks = setup_blocks(page)
    assert blocks[0] == (mine, True)
    assert sorted(p for p, _ in blocks) == ['android', 'desktop', 'ios']
    assert all(not is_open for _, is_open in blocks[1:])          # the others collapsed
    # On /welcome, "How to use it" comes before the intro's first section (§5.4 ¶7).
    assert page.index('id="setup"') < page.index('id="what"')


def test_about_is_the_intro_with_setup_last(env):
    u = env.user()
    page = env.client.get('/about', headers={**u.cookie, 'User-Agent': IPHONE}).text
    order = [page.index(f'id="{s}"') for s in ('what', 'why', 'privacy', 'limits', 'link',
                                                'contact', 'setup')]
    assert order == sorted(order)
    assert setup_blocks(page)[0] == ('ios', True)
    assert env.sql('SELECT welcomed_at FROM users WHERE id = ?', u.id)[0][0] is not None


def limits_section(page):
    """The words of the "Why there are limits" section, tags stripped. Loose on purpose: the
    owner rewrites the copy, and the test should only care where the numbers come from."""
    section = page.split('<section id="limits">')[1].split('</section>')[0]
    return ' '.join(re.sub(r'<[^>]+>', ' ', section).split())


def test_limits_come_from_the_users_row(env):                                   # M6
    u = env.user(daily_limit=7, weekly_limit=31, max_minutes=90)
    for path in ('/welcome', '/about'):
        words = limits_section(env.client.get(path, headers=u.cookie).text)
        numbers = re.findall(r'\d+', words)
        assert '7' in numbers and '31' in numbers and '90 minutes' in words
        assert '5' not in numbers and '20' not in numbers and 'hour' not in words
    d = env.user()
    words = limits_section(env.client.get('/about', headers=d.cookie).text)
    assert {'5', '20'} <= set(re.findall(r'\d+', words)) and '3 hours' in words


def test_intro_page_contents(env):
    u = env.user()
    page = env.client.get('/welcome', headers=u.cookie).text
    assert 'Newsletters' in page                                  # where Proton files the email
    assert 'desloppify@notify.ahdimel.com' in page                # from MAIL_FROM
    assert 'href="mailto:hello@ahdimel.com"' in page
    assert '$' not in page                                        # every placeholder filled
    assert '<script' not in page                                  # nothing to run here


def test_intro_escapes_the_users_name(env):
    u = env.user()
    with env.db() as conn:
        conn.execute('UPDATE users SET name = ? WHERE id = ?', ('<script>x</script>', u.id))
    page = env.client.get('/welcome', headers=u.cookie).text
    assert '<script>x' not in page and '&lt;script&gt;x' in page


@pytest.mark.parametrize('ua, want', [(ANDROID, 'android'), (IPHONE, 'ios'),
                                      ('Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)', 'ios'),
                                      (MAC, 'desktop'), ('', 'desktop'), (None, 'desktop')])
def test_platform(ua, want):
    assert pages.platform(ua) == want


def test_length():
    assert pages.length(180) == '3 hours' and pages.length(60) == '1 hour'
    assert pages.length(90) == '90 minutes'
