"""Turn whatever a friend pasted or shared into one YouTube video ID, or refuse.

Pure: no I/O. The ID is the only thing that leaves this module, and the worker only ever
receives `canonical(id)`, never the input (proposal §5.3, §11 A).
"""
import re
from urllib.parse import parse_qs, urlsplit

MAX_INPUT = 2048

ID = re.compile(r'[A-Za-z0-9_-]{11}')

# Exact host matches only, so lookalikes (youtube.com.evil.com, evilyoutube.com, Cyrillic
# homoglyphs, punycode) fall through.
WATCH_HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'}
SHORT_HOSTS = {'youtu.be', 'www.youtu.be'}
NOCOOKIE_HOSTS = {'youtube-nocookie.com', 'www.youtube-nocookie.com'}
PATH_KINDS = ('shorts', 'live', 'embed', 'v')

# Share text often wraps the link: "Watch this! (https://youtu.be/…)."
WRAPPING = '()[]<>{}"\'.,;!?'


class InvalidURL(ValueError):
    """`reason` is for tests and the friend-facing message; it never carries the input."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def canonical(video_id):
    if not ID.fullmatch(video_id):
        raise InvalidURL('bad_id')
    return f'https://www.youtube.com/watch?v={video_id}'


def video_id(text):
    """The single video ID named in `text`, or InvalidURL.

    Tokens that aren't YouTube video links are ignored, so share text around a link is fine.
    Two links to the same video count as one; two different videos are refused (D4).
    """
    if not isinstance(text, str) or not text.strip():
        raise InvalidURL('empty')
    if len(text) > MAX_INPUT:
        raise InvalidURL('too_long')

    found = []
    for token in text.split():
        for vid in _from_token(token.strip(WRAPPING)):
            if vid not in found:
                found.append(vid)

    if not found:
        raise InvalidURL('no_video')
    if len(found) > 1:
        raise InvalidURL('several_videos')
    return found[0]


def _from_token(token):
    """Every video ID this token names: usually one, none for anything else."""
    if not token:
        return []
    if '://' not in token:
        token = 'https://' + token
    try:
        parts = urlsplit(token)
        port = parts.port
    except ValueError:
        return []
    if parts.scheme.lower() not in ('http', 'https') or port is not None:
        return []
    if '@' in parts.netloc:
        return []
    host = (parts.hostname or '').lower()
    path = parts.path

    if host in SHORT_HOSTS:
        return _id_segment(path)

    if host in NOCOOKIE_HOSTS:
        return _path_kind(path, ('embed',))

    if host in WATCH_HOSTS:
        if path.rstrip('/') == '/watch':
            values = parse_qs(parts.query, keep_blank_values=True).get('v', [])
            return [v for v in values if ID.fullmatch(v)]
        return _path_kind(path, PATH_KINDS)

    return []


def _path_kind(path, kinds):
    segs = [s for s in path.split('/') if s]
    if len(segs) == 2 and segs[0] in kinds and ID.fullmatch(segs[1]):
        return [segs[1]]
    return []


def _id_segment(path):
    segs = [s for s in path.split('/') if s]
    if len(segs) == 1 and ID.fullmatch(segs[0]):
        return [segs[0]]
    return []
