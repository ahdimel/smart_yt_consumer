// "Save as PDF" on the summary page. A file, not inline, because the CSP allows script only
// from 'self'. Without script the button stays hidden: it would do nothing.
document.addEventListener('DOMContentLoaded', function () {
  var button = document.getElementById('save-pdf');
  if (!button) return;
  button.hidden = false;
  button.addEventListener('click', function () { window.print(); });
});
