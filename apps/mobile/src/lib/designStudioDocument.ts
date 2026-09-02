// Builds the document rendered inside Design Studio's WebView — a real
// GrapesJS drag-and-drop canvas, the mobile counterpart to
// apps/desktop/src/components/design-studio/DesignStudio.tsx. Same "big
// inline HTML string" approach as designPreview.ts's buildPreviewDocument
// (this app has no Metro asset-bundling pipeline for .html/.js/.css files
// to load a bundled file instead — see the Design Studio mobile plan).
//
// GrapesJS's own JS/CSS and the grapesjs-blocks-basic plugin are inlined
// from designStudioAssets.generated.ts (produced by
// scripts/generate-design-studio-assets.mjs — re-run that after upgrading
// either package). Desktop's Font Awesome self-hosting fix doesn't apply
// here: rather than also embedding a binary icon font, this uses a small
// custom panel config with plain text button labels ("Blocks"/"Style"/
// "Layers"/"Settings") in place of GrapesJS's default icon-only buttons —
// avoids the font entirely and reads better on a small screen anyway.

import { GJS_BLOCKS_BASIC_JS, GRAPESJS_CSS, GRAPESJS_JS } from "./designStudioAssets.generated";

// Defends against a minified bundle containing a literal "</script"
// substring (e.g. inside a string literal), which would otherwise close
// the surrounding <script> tag early.
function escapeForInlineScript(js: string): string {
  return js.replace(/<\/script/gi, "<\\/script");
}

const BLANK_CANVAS_HTML =
  '<div class="veng-studio-empty">Drag a block from the panel above to start building this page.</div>';

const BOOTSTRAP_SCRIPT = `
(function () {
  var editor = grapesjs.init({
    container: '#gjs',
    height: '100%',
    width: '100%',
    fromElement: false,
    storageManager: false,
    cssIcons: '',
    // Top-level EditorConfig field — NOT nested under canvas.
    nativeDnD: false,
    // Without this, getCss() on save drops any rule not tied to a
    // component currently matched in the canvas (globals, @media queries,
    // utility classes) — silently mutating CSS the user never touched.
    keepUnusedStyles: true,
    components: window.__VENG_INITIAL_HTML__,
    style: window.__VENG_INITIAL_CSS__,
    // Loaded as a plain <script> global (window['gjs-blocks-basic']), not
    // an npm import, so it never self-registers a string plugin id with
    // GrapesJS's plugin manager — pass the function reference directly.
    plugins: [window['gjs-blocks-basic']],
    panels: {
      defaults: [
        {
          id: 'views',
          buttons: [
            { id: 'open-blocks', command: 'open-blocks', label: 'Blocks', active: true, togglable: false },
            { id: 'open-sm', command: 'open-sm', label: 'Style' },
            { id: 'open-layers', command: 'open-layers', label: 'Layers' },
            { id: 'open-tm', command: 'open-tm', label: 'Settings' },
          ],
        },
      ],
    },
  });

  window.__vengaiSave = function () {
    if (window.ReactNativeWebView && window.ReactNativeWebView.postMessage) {
      var nextHtml = editor.getHtml();
      // Saving an untouched blank canvas should not persist the placeholder
      // hint text as if it were real page content.
      var isBlank = !window.__VENG_HAD_HTML__ && nextHtml.indexOf('veng-studio-empty') !== -1;
      window.ReactNativeWebView.postMessage(JSON.stringify({
        source: 'vengaicode-design-studio',
        type: 'saved',
        html: isBlank ? window.__VENG_ORIGINAL_HTML__ : nextHtml,
        css: isBlank ? window.__VENG_ORIGINAL_CSS__ : (editor.getCss() || ''),
      }));
    }
  };

  // Lets the RN side know the (large, inlined) GrapesJS bundle has finished
  // executing and window.__vengaiSave now exists, so the Save button isn't
  // a silent no-op if tapped in the brief window right after the modal opens.
  if (window.ReactNativeWebView && window.ReactNativeWebView.postMessage) {
    window.ReactNativeWebView.postMessage(JSON.stringify({
      source: 'vengaicode-design-studio',
      type: 'ready',
    }));
  }
})();
`;

export function buildDesignStudioDocument(html: string, css: string): string {
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<style>${GRAPESJS_CSS}</style>
<style>
  html, body, #gjs { height: 100%; margin: 0; }
  .gjs-pn-btn { font-size: 11px !important; width: auto !important; padding: 0 8px !important; }
  .veng-studio-empty { padding: 32px 16px; text-align: center; color: #94a3b8; font-family: system-ui, sans-serif; font-size: 13px; }
</style>
</head>
<body>
<div id="gjs"></div>
<script>${escapeForInlineScript(GRAPESJS_JS)}</script>
<script>${escapeForInlineScript(GJS_BLOCKS_BASIC_JS)}</script>
<script>
  window.__VENG_INITIAL_HTML__ = ${escapeForInlineScript(JSON.stringify(html || BLANK_CANVAS_HTML))};
  window.__VENG_INITIAL_CSS__ = ${escapeForInlineScript(JSON.stringify(css || ""))};
  window.__VENG_HAD_HTML__ = ${JSON.stringify(Boolean(html))};
  window.__VENG_ORIGINAL_HTML__ = ${escapeForInlineScript(JSON.stringify(html || ""))};
  window.__VENG_ORIGINAL_CSS__ = ${escapeForInlineScript(JSON.stringify(css || ""))};
</script>
<script>${BOOTSTRAP_SCRIPT}</script>
</body>
</html>`;
}
