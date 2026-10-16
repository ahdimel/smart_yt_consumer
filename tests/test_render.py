"""Renderer safety and shape: lib/week.py inline() / to_html() / render().

Summary text is model output over untrusted input (transcripts, YouTube comments), so the
renderer must never let it become markup. Proposal §11 I4–I9.

Run: python3 -m unittest discover -s tests
"""
import os, re, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib'))
import week as W  # noqa: E402

TAG = re.compile(r'<[^>]*>')


def tags(s):
    """Every HTML tag in s, so assertions can look only at markup, not escaped text."""
    return TAG.findall(s)


class InlineLinks(unittest.TestCase):
    def test_https_link_renders(self):                                         # I7
        out = W.inline('see [the paper](https://example.org/a?b=1&c=2)')
        self.assertIn('<a href="https://example.org/a?b=1&amp;c=2">the paper</a>', out)

    def test_http_link_renders(self):
        self.assertIn('<a href="http://example.org">x</a>', W.inline('[x](http://example.org)'))

    def test_javascript_link_is_text(self):                                    # I4
        for url in ('javascript:alert(1)', 'JAVASCRIPT:alert(1)', ' javascript:alert(1)',
                    'JaVaScRiPt:alert(1)', 'data:text/html,<script>alert(1)</script>',
                    'vbscript:msgbox(1)', '//evil.example/x', 'javascript&#58;alert(1)'):
            with self.subTest(url=url):
                out = W.inline(f'[click]({url})')
                self.assertNotIn('<a', out)
                self.assertIn('click', out)

    def test_quote_cannot_break_out_of_href(self):                             # I5
        out = W.inline('[x](https://a.example/" onmouseover="alert(1))')
        for t in tags(out):
            self.assertNotIn('onmouseover', t)

    def test_quote_breakout_without_scheme(self):                              # I5
        out = W.inline('[x](" onmouseover="alert(1))')
        for t in tags(out):
            self.assertNotIn('onmouseover', t)

    def test_link_url_with_markup_inside_is_text(self):
        out = W.inline('[x](https://a.example/`code`)')
        self.assertNotIn('<a', out)


class InlineEscaping(unittest.TestCase):
    def test_raw_html_is_escaped(self):                                        # I6
        for raw in ('<img src=x onerror=alert(1)>', '<script>alert(1)</script>',
                    '<a href="javascript:alert(1)">x</a>', '<svg onload=alert(1)>'):
            with self.subTest(raw=raw):
                out = W.inline(raw)
                self.assertEqual(tags(out), [])

    def test_escaped_html_inside_emphasis_stays_escaped(self):
        out = W.inline('**<b onclick=x>bold</b>**')
        self.assertEqual([t for t in tags(out) if t not in ('<strong>', '</strong>')], [])

    def test_timestamp_becomes_chip(self):                                     # I7
        self.assertIn('<span class="ts">14:32</span>', W.inline('at `14:32` he says'))
        self.assertIn('<span class="ts">1:02:03</span>', W.inline('`1:02:03`'))

    def test_non_timestamp_code_is_mono(self):
        self.assertIn('<span class="mono">x &lt; y</span>', W.inline('`x < y`'))

    def test_emphasis(self):
        out = W.inline('**bold** and *em*')
        self.assertIn('<strong>bold</strong>', out)
        self.assertIn('<em>em</em>', out)

    def test_apostrophes_render(self):
        # quote escaping must not leave visible entities double-escaped
        out = W.inline("it's \"quoted\"")
        self.assertNotIn('&amp;', out)


class BlockShape(unittest.TestCase):
    def test_contest_section_styled(self):                                     # I8
        out = W.to_html('Body.\n\n## What the comments contest\n\n- a correction')
        self.assertIn('<section class="contested"><h3>What the comments contest</h3>', out)
        self.assertTrue(out.rstrip().endswith('</section>'))

    def test_one_line_summary(self):                                           # I9
        out = W.to_html('This video contains one claim: X. Nothing else survives.')
        self.assertEqual(out, '<p>This video contains one claim: X. Nothing else survives.</p>')

    def test_heading_text_escaped(self):
        out = W.to_html('## <img src=x onerror=alert(1)>')
        self.assertEqual([t for t in tags(out) if not t.startswith(('<h', '</h'))], [])


class RenderPage(unittest.TestCase):
    """Front-matter fields reach the page through render(); they must be escaped too."""

    def render(self, front, body='Body text.\n\n## What the comments contest\n\nNothing.'):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'abcdefghijk.md'), 'w', encoding='utf-8') as f:
                f.write('---\n' + front + '\nadded: 2026-10-15T00:00:00\n---\n\n' + body + '\n')
            return W.render(d, '2026-W42')

    def test_malicious_front_matter_escaped(self):
        page = self.render('nav: <b>x</b>\ntitle: <script>alert(1)</script>\n'
                           'channel: <img src=x onerror=alert(1)>\n'
                           'verdict: **Skim.** [x](javascript:alert(1)) "><svg onload=alert(1)>\n'
                           'fluff: 5%"><script>alert(2)</script>\nwatchable: ~1 of 2 min')
        self.assertNotIn('<script>alert', page)
        self.assertNotIn('onerror=alert', ''.join(tags(page)))
        self.assertNotIn('onload=alert', ''.join(tags(page)))
        self.assertNotIn('href="javascript', page)

    def test_normal_summary_renders(self):
        page = self.render('nav: Rare earths\ntitle: China Found Something Better Than Oil\n'
                           'channel: Maxinomics\nverdict: **Watch it.** Dense.\nfluff: 6%\n'
                           'watchable: ~25 of 27 min')
        self.assertIn('<h2>China Found Something Better Than Oil</h2>', page)
        self.assertIn('<b>6% fluff</b>', page)
        self.assertIn('https://youtu.be/abcdefghijk', page)


if __name__ == '__main__':
    unittest.main()
