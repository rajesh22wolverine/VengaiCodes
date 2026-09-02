import { useEffect, useRef } from "react";
import grapesjs, { type Editor } from "grapesjs";
import gjsBlocksBasic from "grapesjs-blocks-basic";
import { Save, X } from "lucide-react";
import "grapesjs/dist/css/grapes.min.css";
// GrapesJS's default panel buttons (Style/Layer/Block Manager icons) are
// Font Awesome 4.7 glyph classes. By default it loads that from a CDN
// (cssIcons below), which this app's CSP blocks — self-host it instead so
// nothing but same-origin/bundled assets ever gets requested.
import "font-awesome/css/font-awesome.min.css";
import "./design-studio.css";

const BLANK_CANVAS_HTML =
  '<div class="veng-studio-empty">Drag a block from the right panel to start building this page.</div>';

interface DesignStudioProps {
  html: string;
  css: string;
  onSave: (html: string, css: string) => void;
  onClose: () => void;
}

// A real drag-and-drop visual canvas for a page's HTML/CSS — the
// counterpart to the click-to-edit live preview elsewhere in the UI/UX
// phase, which can only adjust elements that already exist. GrapesJS's
// native output (plain HTML + a CSS stylesheet) matches exactly what
// build_design_to_code_prompt/build_screen_to_code_prompt already produce,
// so Save just writes into the same generated_html/generated_css fields
// every other page-editing path in this screen already uses.
export default function DesignStudio({ html, css, onSave, onClose }: DesignStudioProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<Editor | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const editor = grapesjs.init({
      container: containerRef.current,
      height: "100%",
      width: "100%",
      fromElement: false,
      storageManager: false,
      cssIcons: "",
      // GrapesJS defaults to native HTML5 drag-and-drop for the block
      // panel; its own JS-simulated drag (mouse events, not browser DnD)
      // behaves more consistently across browsers/OSes for a block palette
      // like this one. Top-level EditorConfig field — NOT nested under
      // canvas (CanvasConfig has no nativeDnD field at all).
      nativeDnD: false,
      components: html || BLANK_CANVAS_HTML,
      style: css,
      plugins: [gjsBlocksBasic],
      // Without this, getCss() on save drops any rule not tied to a
      // component currently matched in the canvas (globals, @media queries,
      // utility classes) — silently mutating CSS the user never touched.
      keepUnusedStyles: true,
    });
    editorRef.current = editor;

    return () => {
      editor.destroy();
      editorRef.current = null;
    };
    // Only mount once per time Design Studio is opened — html/css are the
    // starting point for the canvas, not a value to keep re-syncing into it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSave = () => {
    const editor = editorRef.current;
    if (!editor) return;
    const nextHtml = editor.getHtml();
    // Saving an untouched blank canvas should not persist the placeholder
    // hint text as if it were real page content.
    if (!html && nextHtml.includes("veng-studio-empty")) {
      onSave(html, css);
      return;
    }
    onSave(nextHtml, editor.getCss() || "");
  };

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[var(--color-background)]">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)] bg-[var(--color-surface)] flex-shrink-0">
        <p className="text-sm font-semibold text-[var(--color-text-primary)]">Design Studio</p>
        <div className="flex items-center gap-2">
          <button
            onClick={handleSave}
            className="px-4 py-2 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors flex items-center gap-2"
          >
            <Save className="w-4 h-4" />
            Save & Close
          </button>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-[var(--color-surface-raised)] transition-colors"
            title="Close without saving"
          >
            <X className="w-4 h-4 text-[var(--color-text-secondary)]" />
          </button>
        </div>
      </div>
      <div className="veng-studio-root flex-1 min-h-0">
        <div ref={containerRef} className="h-full w-full" />
      </div>
    </div>
  );
}
