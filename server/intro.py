"""The words on /welcome and /about (proposal §5.4). DRAFT, written by Claude from §5.4's outline:
the owner rewrites all of it in their own voice before anyone is invited.

Editing guide. Each block is an HTML fragment; change the words freely. `$daily`, `$weekly` and
`$max_length` are filled from the friend's own row (§11 M6), `$bookmarklet` is the bookmarklet's
link and `$sender` the address summaries come from. To write a literal dollar sign, type `$$`.
Keep the `<h2>` headings and the `id=` attributes: the tests and the page layout look for them.
"""

# §5.4 sections 1–6, in order. Section 7, "How to use it", is SETUP below.
INTRO = [
    ('what', """
<h2>What this is</h2>
<p>Paste a YouTube link, get back what the video actually says. The summary is as long as the
video's real claims need, so a padded twenty-minute video can come back as a single line, and a
dense lecture as a full page.</p>
<p>Every summary starts with three fields:</p>
<dl>
  <dt>Verdict</dt><dd>Whether to watch it, skim it or skip it, and why.</dd>
  <dt>Watchable</dt><dd>How many minutes are worth watching, out of the whole runtime.</dd>
  <dt>Fluff</dt><dd>The share of the runtime that is ad reads, teasers, recaps and filler.</dd>
</dl>
<p>It ends with what the comments contest: the corrections and pushback viewers posted.</p>
"""),
    ('why', """
<h2>Why I built it</h2>
<p>Most long-form video is padded to keep you watching. The padding is measurable: in five videos
I tested, it ran from under 1% of a two-hour lecture to 34% of a nineteen-minute listicle. And the
comments often catch what the video got wrong. I wanted the claims and the corrections without
the hour.</p>
"""),
    ('privacy', """
<h2>What I can and can't see</h2>
<p>I can see that you made a request, when, and how much of my subscription it used. I can't see
which video, its title, or the summary: not on my admin page, not in any log, not in my email
account. Everything about the video is deleted after 30 days.</p>
<p>To be honest about the limits of that: this is how I built it, not a cryptographic guarantee.
The data sits on a server I control, and I've chosen never to look.</p>
"""),
    ('limits', """
<h2>Why there are limits</h2>
<p>It runs on my personal Claude subscription, which I also use for my own work, and each summary
uses a real share of it. Your limits are $daily a day and $weekly a week, for videos up to
$max_length long. Ask if you need more.</p>
"""),
    ('link', """
<h2>Please don't share your link</h2>
<p>Your invite link <em>is</em> your login. Anyone holding it uses your requests and gets
summaries sent to your email. If you'd like a friend added, ask me and they'll get their own. If
your link leaks, tell me: I'll switch it off and send you a new one, no questions asked.</p>
"""),
    ('contact', """
<h2>How to reach me</h2>
<p>Email <a href="mailto:hello@ahdimel.com">hello@ahdimel.com</a>. Replying to any summary email
reaches me too.</p>
"""),
]

# §5.4 section 7. Shown above everything on /welcome, last on /about.
SETUP_HEADING = """
<h2>How to use it</h2>
<p>Each browser signs in on its own: open your invite link once in every browser you'll use
(Safari and Chrome on the same phone count as two).</p>
<p>When a summary is ready, an email arrives from <strong>$sender</strong> with the video's title
and a link. <strong>Proton Mail files it under Newsletters</strong>, so look there for the first
one, and add the address to your contacts so later ones reach your inbox. Each summary stays up
for 30 days, and its page has a Save as PDF button.</p>
"""

# One block per platform. /welcome opens the visitor's own and collapses the rest (§11 M5).
SETUP = {
    'android': ('Android phone', """
<ol>
  <li>On this page in Chrome, tap the <strong>⋮</strong> menu, then <strong>Install app</strong>
      (on some phones: <strong>Add to Home screen</strong>, then <strong>Install</strong>).</li>
  <li>In the YouTube app, tap <strong>Share</strong> under a video and choose
      <strong>desloppify</strong> from the list (it may be under <strong>More</strong>).</li>
  <li>Your page opens and says it's queued. That's it.</li>
</ol>
"""),
    'ios': ('iPhone or iPad', """
<ol>
  <li>In the YouTube app, tap <strong>Share</strong> under a video, then
      <strong>Copy link</strong>.</li>
  <li>Open your page here and tap <strong>Paste and summarize</strong>. Your iPhone asks
      first: tap the small <strong>Paste</strong> bubble.</li>
</ol>
<p>To keep it one tap away: on your page in Safari, tap <strong>Share</strong>, then
<strong>Add to Home Screen</strong>. The icon opens your page, already signed in.</p>
"""),
    'desktop': ('Computer', """
<ol>
  <li>Drag this button to your bookmarks bar:
      <a class="bookmarklet" href="$bookmarklet">Summarize</a>.
      (If you can't see the bar: Ctrl+Shift+B, or ⌘⇧B on a Mac.)</li>
  <li>On a YouTube video's page, click <strong>Summarize</strong> in the bar. A tab opens,
      sends the video, and says it's queued. Close it when you like.</li>
</ol>
<p>Or copy the video's address and use <strong>Paste and summarize</strong> on your page.</p>
"""),
}
