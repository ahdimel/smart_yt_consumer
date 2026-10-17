// "Paste and summarize" on the home page: read the clipboard and submit the paste box with it.
// A file, not inline, because the CSP allows script only from 'self'. Without script, or a
// browser without the async clipboard, the button stays hidden and the box works as before.
//
// Only text that mentions a YouTube host is put in the box and sent. The clipboard can hold
// anything (a password, an address), and none of that should leave the device.
document.addEventListener('DOMContentLoaded', function () {
  var button = document.getElementById('paste');
  var input = document.getElementById('url');
  var hint = document.getElementById('paste-hint');
  if (!button || !input || !input.form || !navigator.clipboard || !navigator.clipboard.readText) return;
  var YOUTUBE = /(^|[^a-z0-9.-])(www\.|m\.|music\.)?(youtube\.com|youtu\.be|youtube-nocookie\.com)\//i;

  function say(text) {
    hint.textContent = text;
    hint.hidden = false;
  }

  button.hidden = false;
  button.addEventListener('click', function () {
    navigator.clipboard.readText().then(function (text) {
      text = (text || '').trim();
      if (!text) {
        say('The clipboard is empty. Copy the video’s link first (in YouTube: Share, then Copy link).');
      } else if (!YOUTUBE.test(text)) {
        say('The clipboard doesn’t hold a YouTube link. Copy the video’s link first (in YouTube: Share, then Copy link).');
      } else {
        input.value = text;
        input.form.submit();
      }
    }, function () {
      say('Couldn’t read the clipboard. Tap the box, choose Paste, then Summarize.');
      input.focus();
    });
  });
});
