// Runs one of server/static/*.js in a stub DOM and prints what it did, as JSON.
// Usage: node js_harness.js <script> '<config json>'
//   config: {hash, clipboard, clipboardFails, noClipboard, response: {status, body}, fetchFails,
//            opener, click}
// Only what the scripts touch is stubbed. The point is to see their requests and messages, so
// the Python tests can replay the request against the real app (§11 J5).
const fs = require('fs');
const vm = require('vm');

const [script, raw] = process.argv.slice(2);
const cfg = JSON.parse(raw || '{}');
const out = { fetches: [], replaced: [], submitted: false, closed: false };
const listeners = {};

function element(id, extra) {
  const el = Object.assign({ id, hidden: id === 'paste' || id === 'add-close' || id === 'paste-hint',
                             textContent: '', value: '', handlers: {} }, extra || {});
  el.addEventListener = (type, fn) => { el.handlers[type] = fn; };
  el.focus = () => { out.focused = id; };
  return el;
}
const form = { submit: () => { out.submitted = true; } };
const els = {
  'paste': element('paste'), 'url': element('url', { form }), 'paste-hint': element('paste-hint'),
  'add-status': element('add-status', { textContent: 'Sending…' }), 'add-close': element('add-close'),
};

const sandbox = {
  document: {
    getElementById: (id) => els[id] || null,
    addEventListener: (type, fn) => { listeners[type] = fn; },
  },
  location: { hash: cfg.hash || '', pathname: '/add' },
  history: { replaceState: (s, t, u) => { out.replaced.push(u); } },
  navigator: cfg.noClipboard ? {} : { clipboard: { readText: () =>
    cfg.clipboardFails ? Promise.reject(new Error('denied')) : Promise.resolve(cfg.clipboard || '') } },
  fetch: (url, init) => {
    out.fetches.push({ url, method: init.method, headers: init.headers, body: init.body,
                       credentials: init.credentials });
    if (cfg.fetchFails) return Promise.reject(new TypeError('network'));
    const r = cfg.response || { status: 202, body: { status: 'queued' } };
    return Promise.resolve({ ok: r.status >= 200 && r.status < 300, status: r.status,
                             json: () => r.body === undefined ? Promise.reject(new Error('not json'))
                                                              : Promise.resolve(r.body) });
  },
  console,
};
sandbox.window = { opener: cfg.opener ? {} : null, close: () => { out.closed = true; } };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(script, 'utf8'), sandbox, { filename: script });
if (listeners.DOMContentLoaded) listeners.DOMContentLoaded();
if (cfg.click && els[cfg.click].handlers.click) els[cfg.click].handlers.click();

setTimeout(() => {
  for (const [id, el] of Object.entries(els)) {
    out[id] = { hidden: el.hidden, text: el.textContent, value: el.value };
  }
  console.log(JSON.stringify(out));
}, 20);
