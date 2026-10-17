// The bookmarklet's landing page, /add#<video link>. The link travels in the #fragment, which
// browsers never send to the server, so it appears in no request path, query string or log
// (§11 J5). This script reads it, wipes it from the address bar and history, and POSTs it to the
// same endpoint as the paste box. A file, not inline, because the CSP allows script only from
// 'self'.
document.addEventListener('DOMContentLoaded', function () {
  var status = document.getElementById('add-status');
  var close = document.getElementById('add-close');
  var MESSAGES = {
    401: 'This browser isn’t signed in. Open your invite link in it once, then try again.',
    403: 'The request was refused. Open your page and paste the link there instead.',
    413: 'That was too long to be a YouTube link.',
    429: 'Too many attempts. Try again in a few minutes.'
  };

  function show(text) {
    status.textContent = text;
    // Opened by the bookmarklet's open(), so the tab may close itself.
    if (window.opener && close) {
      close.hidden = false;
      close.addEventListener('click', function () { window.close(); });
    }
  }

  var raw = location.hash.slice(1);
  history.replaceState(null, '', location.pathname);
  var link;
  try { link = decodeURIComponent(raw); } catch (e) { link = raw; }
  if (!link.trim()) {
    show('Nothing to send. Click Summarize in your bookmarks bar while a YouTube video is open.');
    return;
  }

  fetch('/api/requests', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: link })
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (body) {
      if (r.ok) {
        show(body.status === 'done' ? 'Done. The email is on its way.'
                                    : 'Queued. You’ll get an email when it’s ready.');
      } else {
        show(body.message || MESSAGES[r.status] || 'Not sent. Try again later.');
      }
    });
  }, function () {
    show('Couldn’t reach the server. Check your connection and try again.');
  });
});
