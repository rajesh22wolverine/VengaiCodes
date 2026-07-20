// Builds the live-preview document rendered inside the design-to-code
// WebView (see designPreview.ts in apps/desktop for the identical
// counterpart, which targets an iframe instead — duplicated rather than
// shared since neither app currently depends on a shared workspace
// package for runtime code).
//
// The returned document embeds a small vanilla-JS editor bridge that:
// - lets the user tap any element to select it (outlined, sent to the
//   host via postMessage with its computed styles)
// - makes text elements contentEditable in place so typing directly
//   edits the rendered page
// - applies style/placeholder/text commands sent back from the host
// - reports the resulting body innerHTML back to the host after any
//   change, debounced, so the host's HTML state stays in sync
//
// Every reload gets fresh `data-veng-id` attributes, so the host must
// treat a `ready` message as "selection no longer valid".

export interface PreviewSelection {
  id: string;
  tag: string;
  isField: boolean;
  text: string | null;
  placeholder: string | null;
  styles: {
    color: string | null;
    backgroundColor: string | null;
    fontSize: number;
    fontWeight: string;
    textAlign: string;
  };
}

const EDITOR_SCRIPT = `
(function () {
  var SOURCE = 'vengaicode-preview';
  var selectedEl = null;
  var changeTimer = null;

  function post(msg) {
    var payload = JSON.stringify(Object.assign({ source: SOURCE }, msg));
    if (window.ReactNativeWebView && window.ReactNativeWebView.postMessage) {
      window.ReactNativeWebView.postMessage(payload);
    } else if (window.parent) {
      window.parent.postMessage(payload, '*');
    }
  }

  function rgbToHex(rgb) {
    if (!rgb || rgb === 'transparent') return null;
    var m = rgb.match(/rgba?\\(([^)]+)\\)/);
    if (!m) return null;
    var parts = m[1].split(',').map(function (s) { return parseFloat(s.trim()); });
    if (parts.length === 4 && parts[3] === 0) return null;
    return '#' + parts.slice(0, 3).map(function (n) {
      var h = Math.round(n).toString(16);
      return h.length === 1 ? '0' + h : h;
    }).join('');
  }

  function serializeStyles(el) {
    var cs = window.getComputedStyle(el);
    return {
      color: rgbToHex(cs.color),
      backgroundColor: rgbToHex(cs.backgroundColor),
      fontSize: parseInt(cs.fontSize, 10) || 16,
      fontWeight: cs.fontWeight,
      textAlign: cs.textAlign,
    };
  }

  function idOf(el) {
    var existing = el.getAttribute('data-veng-id');
    if (existing) return existing;
    var id = 'v' + Math.random().toString(36).slice(2, 10);
    el.setAttribute('data-veng-id', id);
    return id;
  }

  function notifyContentChanged() {
    clearTimeout(changeTimer);
    changeTimer = setTimeout(function () {
      post({ type: 'content-changed', html: document.body.innerHTML });
    }, 250);
  }

  function clearSelection() {
    if (selectedEl) {
      selectedEl.removeAttribute('contenteditable');
      selectedEl.classList.remove('__veng_selected');
    }
    selectedEl = null;
  }

  function selectElement(el) {
    clearSelection();
    selectedEl = el;
    el.classList.add('__veng_selected');
    var isField = el.tagName === 'INPUT' || el.tagName === 'TEXTAREA';
    post({
      type: 'select',
      id: idOf(el),
      tag: el.tagName.toLowerCase(),
      isField: isField,
      text: isField ? null : el.innerText,
      placeholder: isField ? (el.getAttribute('placeholder') || '') : null,
      styles: serializeStyles(el),
    });
    if (!isField && el.tagName !== 'IMG') {
      el.setAttribute('contenteditable', 'true');
      el.focus();
    }
  }

  document.addEventListener('click', function (e) {
    var link = e.target.closest && e.target.closest('a');
    if (link) e.preventDefault();
    var btn = e.target.closest && e.target.closest('button');
    if (btn) e.preventDefault();

    var el = e.target;
    if (el === document.body || el === document.documentElement) {
      clearSelection();
      post({ type: 'deselect' });
      return;
    }
    e.stopPropagation();
    selectElement(el);
  }, true);

  document.addEventListener('submit', function (e) { e.preventDefault(); }, true);

  document.addEventListener('input', function (e) {
    if (e.target === selectedEl) notifyContentChanged();
  }, true);

  function applyCommand(cmd) {
    if (!selectedEl) return;
    if (cmd.type === 'set-style') {
      selectedEl.style[cmd.prop] = cmd.value;
      notifyContentChanged();
    } else if (cmd.type === 'set-placeholder') {
      selectedEl.setAttribute('placeholder', cmd.value);
      notifyContentChanged();
    } else if (cmd.type === 'deselect') {
      clearSelection();
    }
  }

  function handleIncoming(event) {
    try {
      var data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
      if (data && data.source === 'vengaicode-editor') applyCommand(data);
    } catch (err) {}
  }
  document.addEventListener('message', handleIncoming);
  window.addEventListener('message', handleIncoming);

  post({ type: 'ready' });
})();
`;

export function buildPreviewDocument(html: string, css: string): string {
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { margin: 0; }
.__veng_selected { outline: 2px solid #f97316 !important; outline-offset: 1px; cursor: text; }
${css}
</style>
</head>
<body>
${html}
<script>${EDITOR_SCRIPT}</script>
</body>
</html>`;
}
