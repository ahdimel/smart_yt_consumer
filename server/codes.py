"""Job error codes: retry policy and what the friend is told (proposal §5.5)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Code:
    max_attempts: int        # 1 = permanent: fail on first report
    backoff: tuple = ()      # seconds before attempt n+1, indexed by attempts so far - 1
    message: str = ''


MIN = 60

CODES = {
    'unavailable': Code(1, message="The video isn't publicly available."),
    'members_only': Code(1, message='The video is for channel members only.'),
    'age_restricted': Code(1, message='The video is age-restricted.'),
    'live_or_upcoming': Code(1, message='Try again after the stream ends.'),
    'no_captions': Code(1, message='No captions, so nothing to summarize.'),
    'too_long': Code(1, message='Longer than your limit.'),
    # The 45-minute step in §5.5 would follow a third failure, which is already final.
    'fetch_failed': Code(3, (5 * MIN, 15 * MIN), "Couldn't fetch the video."),
    'rate_limited': Code(3, (5 * MIN, 15 * MIN), "YouTube refused to serve the video."),
    'summarize_failed': Code(2, (5 * MIN,), 'The summarizer failed on this video.'),
    'invalid_output': Code(2, (5 * MIN,), 'The summarizer produced something unusable.'),
}

INVALID_URL_MESSAGE = "That doesn't look like a single YouTube video."
SEVERAL_VIDEOS_MESSAGE = 'That names more than one video. One at a time, please.'
