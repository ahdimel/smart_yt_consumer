"""§11 A: URL validation. Pure, no app."""
import pytest

from server.urls import InvalidURL, canonical, video_id

ID = 'dQw4w9WgXcQ'


def ok(text, expect=ID):
    assert video_id(text) == expect


def bad(text, reason=None):
    with pytest.raises(InvalidURL) as e:
        video_id(text)
    if reason:
        assert e.value.reason == reason


@pytest.mark.parametrize('text', [
    f'https://www.youtube.com/watch?v={ID}',                                     # A1
    f'http://www.youtube.com/watch?v={ID}',                                      # A2
    f'youtube.com/watch?v={ID}',
    f'www.youtube.com/watch?v={ID}',
    f'https://youtube.com/watch?v={ID}',
    f'https://m.youtube.com/watch?v={ID}',                                       # A3
    f'https://music.youtube.com/watch?v={ID}',
    f'https://YOUTUBE.COM/watch?v={ID}',
    f'HTTPS://WWW.YouTube.com/watch?v={ID}',
    f'https://youtu.be/{ID}',                                                    # A4
    f'https://youtu.be/{ID}?t=42',
    f'https://youtu.be/{ID}?si=AbCdEfGh123',
    f'youtu.be/{ID}',
    f'https://www.youtube.com/shorts/{ID}',                                      # A5
    f'https://www.youtube.com/live/{ID}',
    f'https://www.youtube.com/live/{ID}?feature=share',
    f'https://www.youtube.com/embed/{ID}',
    f'https://www.youtube.com/v/{ID}',
    f'https://www.youtube-nocookie.com/embed/{ID}',
    f'https://www.youtube.com/watch?feature=share&v={ID}',                      # A6
    f'https://www.youtube.com/watch?v={ID}&t=1h2m3s',
    f'https://www.youtube.com/watch?v={ID}&list=PLabcdefghijklmnop&index=3',
    f'https://www.youtube.com/watch?list=PLabcdefghijklmnop&v={ID}&index=3',
    f'  https://youtu.be/{ID}  ',                                                # A8
    f'\nhttps://youtu.be/{ID}\n',
    f'Watch this! https://youtu.be/{ID}',
    f'Great talk (https://youtu.be/{ID}).',
    f'"Some title" by Someone\nhttps://youtu.be/{ID}?si=x\nShared from YouTube',
    f'https://youtu.be/{ID} https://www.youtube.com/watch?v={ID}',              # A9
    f'https://www.youtube.com/watch?v={ID}&v={ID}',
])
def test_accepts(text):
    ok(text)


@pytest.mark.parametrize('vid', ['a-b_c-d_e-f', '___________', 'AbC-123_xYz'])  # A7
def test_ids_with_dash_and_underscore(vid):
    ok(f'https://youtu.be/{vid}', vid)
    ok(f'https://www.youtube.com/watch?v={vid}', vid)


@pytest.mark.parametrize('text', ['', '   ', '\n\t', 'x' * 2049,                 # A10
                                  f'https://youtu.be/{ID} ' + 'x' * 2048])
def test_rejects_empty_and_oversize(text):
    bad(text)


@pytest.mark.parametrize('text', [                                               # A11
    f'https://vimeo.com/{ID}',
    f'https://www.youtube.com.evil.com/watch?v={ID}',
    f'https://evilyoutube.com/watch?v={ID}',
    f'https://youtube.com@evil.com/watch?v={ID}',
    f'https://user:pw@youtube.com/watch?v={ID}',
    f'https://уoutube.com/watch?v={ID}',                 # Cyrillic у
    f'https://xn--outube-4nf.com/watch?v={ID}',
    f'https://youtu.be.evil.com/{ID}',
    f'https://www.youtube.com:8443/watch?v={ID}',
    f'https://evil.com/?next=https://youtu.be/{ID}',
    f'https://evil.com/youtu.be/{ID}',
    f'ftp://youtube.com/watch?v={ID}',
])
def test_rejects_other_hosts(text):
    bad(text)


@pytest.mark.parametrize('text', [                                               # A12
    'https://www.youtube.com/playlist?list=PLabcdefghijklmnop',
    'https://www.youtube.com/@somechannel',
    'https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv',
    'https://www.youtube.com/results?search_query=cats',
    'https://www.youtube.com/',
    'https://www.youtube.com',
    'https://youtu.be/',
    f'https://www.youtube.com/watch/{ID}',
    f'https://www.youtube.com/shorts/{ID}/extra',
    f'https://www.youtube-nocookie.com/watch?v={ID}',
])
def test_rejects_non_video_pages(text):
    bad(text)


@pytest.mark.parametrize('text', [                                               # A13
    'https://youtu.be/dQw4w9WgXc',                    # 10
    'https://youtu.be/dQw4w9WgXcQQ',                  # 12
    'https://www.youtube.com/watch?v=dQw4w9WgXc',
    'https://www.youtube.com/watch?v=dQw4w9WgXcQQ',
    'https://www.youtube.com/watch?v=dQw4w9W.XcQ',
    'https://www.youtube.com/watch?v=dQw4w9W%20cQ',
    'https://www.youtube.com/watch?v=dQw4w9Wｇ XcQ',
    'https://www.youtube.com/watch?v=',
    'https://www.youtube.com/watch?v',
    'https://www.youtube.com/watch',
])
def test_rejects_malformed_ids(text):
    bad(text)


@pytest.mark.parametrize('text', [                                               # A14
    '--exec=touch /tmp/pwned',
    '-o /tmp/x',
    f'-{ID}',
    ID,                                   # a bare ID is not a link
    'https://youtu.be/dQw4w9;rm-rf',
    'https://www.youtube.com/watch?v=dQw4w9$(id)',
    'https://www.youtube.com/watch?v=`id`dQw4w9Wg',
    'https://youtu.be/dQw4w9WgX|Q',
    'javascript:alert(1)',
    f'javascript://youtu.be/{ID}',
    f'javascript:alert("https://youtu.be/{ID}")',
    f'data:text/html,https://youtu.be/{ID}',
])
def test_rejects_injection(text):
    bad(text)


def test_dash_leading_id_is_safe_because_argv_is_the_canonical_url():          # A14
    # Real IDs can start with '-'. The injection risk is an argv value starting with '-';
    # the worker only ever passes canonical(), which starts with https://.
    assert video_id('https://youtu.be/-bcdefghijk') == '-bcdefghijk'
    assert canonical('-bcdefghijk') == 'https://www.youtube.com/watch?v=-bcdefghijk'


@pytest.mark.parametrize('text', [                                               # A15
    f'https://youtu.be/{ID} https://youtu.be/aaaaaaaaaaa',
    f'https://www.youtube.com/watch?v={ID}&v=aaaaaaaaaaa',
])
def test_rejects_two_different_videos(text):
    bad(text, 'several_videos')


def test_canonical():                                                            # A16
    for text in (f'youtu.be/{ID}?t=1', f'https://m.youtube.com/shorts/{ID}',
                 f'Look: https://www.youtube.com/watch?feature=x&v={ID}&list=PL1'):
        assert canonical(video_id(text)) == f'https://www.youtube.com/watch?v={ID}'
    for junk in ('', 'short', '-o /tmp/x__', ID + 'x'):
        with pytest.raises(InvalidURL):
            canonical(junk)
