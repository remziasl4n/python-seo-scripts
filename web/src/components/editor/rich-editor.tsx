"use client";

/**
 * The writing area: a Tiptap editor with headings, lists and links, a toolbar, the
 * highlighting of one chosen word or phrase, and hints in empty sections saying what to
 * write there (from the brief).
 */
import type { Node as PMNode } from "@tiptap/pm/model";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import { type Editor, EditorContent, Extension, useEditor, useEditorState } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  Bold,
  Heading1,
  Heading2,
  Heading3,
  Italic,
  Link2,
  List,
  ListOrdered,
  Pilcrow,
  Quote,
  Redo2,
  Undo2,
} from "lucide-react";
import { type ReactNode, useEffect, useRef } from "react";

import { cn } from "@/lib/cn";
import { findTerm } from "@/lib/editor";

// --- Highlighting a word or phrase -------------------------------------------------------

interface HighlightState {
  term: string | null;
  set: DecorationSet;
}

const highlightKey = new PluginKey<HighlightState>("termHighlight");

function decorate(doc: PMNode, term: string | null): DecorationSet {
  if (!term) return DecorationSet.empty;
  const decorations: Decoration[] = [];
  doc.descendants((node, pos) => {
    if (!node.isTextblock) return true;
    // The block's text, with the document position of every character
    let text = "";
    const positions: number[] = [];
    node.forEach((child, offset) => {
      const start = pos + 1 + offset;
      if (child.isText && child.text) {
        for (let i = 0; i < child.text.length; i++) positions.push(start + i);
        text += child.text;
      } else {
        positions.push(start);
        text += " ";
      }
    });
    for (const [from, to] of findTerm(text, term)) {
      const start = positions[from];
      const end = positions[to - 1];
      if (start !== undefined && end !== undefined) {
        decorations.push(Decoration.inline(start, end + 1, { class: "term-highlight" }));
      }
    }
    return false;
  });
  return DecorationSet.create(doc, decorations);
}

const TermHighlight = Extension.create({
  name: "termHighlight",
  addProseMirrorPlugins() {
    return [
      new Plugin<HighlightState>({
        key: highlightKey,
        state: {
          init: (): HighlightState => ({ term: null, set: DecorationSet.empty }),
          apply(tr, value, _old, state) {
            const meta = tr.getMeta(highlightKey) as string | null | undefined;
            const term = meta === undefined ? value.term : meta;
            if (meta !== undefined || tr.docChanged) return { term, set: decorate(state.doc, term) };
            return value;
          },
        },
        props: { decorations: (state) => highlightKey.getState(state)?.set },
      }),
    ];
  },
});

export function highlightTerm(editor: Editor, term: string | null) {
  editor.view.dispatch(editor.state.tr.setMeta(highlightKey, term));
  if (!term) return;
  const first = editor.view.dom.querySelector(".term-highlight");
  first?.scrollIntoView({ block: "center", behavior: "smooth" });
}

// --- Hints in empty sections ------------------------------------------------------------

const GENERIC_HINT = "Answer the heading's question in the first sentence, then add the detail.";

function hintBlock(text: string): HTMLElement {
  const element = document.createElement("div");
  element.className = "section-hint";
  element.contentEditable = "false";
  element.textContent = text;
  return element;
}

/**
 * Help in empty places: "Heading" in an empty heading, a prompt in an empty draft, and
 * under a heading with nothing written yet, what the brief says to cover there (as a
 * block of its own, so long notes never overlap the next heading). Worked out afresh on
 * every change, so the notes appear as soon as the brief loads.
 */
const SectionHints = Extension.create<{ hintFor: (heading: string) => string | undefined }>({
  name: "sectionHints",
  addOptions: () => ({ hintFor: () => undefined }),
  addProseMirrorPlugins() {
    const { hintFor } = this.options;
    return [
      new Plugin({
        key: new PluginKey("sectionHints"),
        props: {
          decorations: ({ doc }) => {
            const blank = doc.childCount === 1 && doc.firstChild?.content.size === 0;
            const decorations: Decoration[] = [];
            let previous: PMNode | null = null;
            doc.forEach((node, pos) => {
              if (node.isTextblock && node.content.size === 0) {
                const short = blank
                  ? "Start writing, or paste your draft here…"
                  : node.type.name === "heading"
                    ? "Heading"
                    : "";
                if (short) {
                  decorations.push(
                    Decoration.node(pos, pos + node.nodeSize, { class: "is-empty", "data-placeholder": short }),
                  );
                } else if (previous?.type.name === "heading") {
                  const text = hintFor(previous.textContent) ?? GENERIC_HINT;
                  decorations.push(Decoration.widget(pos, () => hintBlock(text), { side: -1, key: `hint:${text}` }));
                }
              }
              previous = node;
            });
            return DecorationSet.create(doc, decorations);
          },
        },
      }),
    ];
  },
});

// --- Finding and adding sections ---------------------------------------------------------

interface HeadingAt {
  pos: number;
  level: number;
  text: string;
}

function headings(doc: PMNode): HeadingAt[] {
  const found: HeadingAt[] = [];
  doc.forEach((node, pos) => {
    if (node.type.name === "heading") {
      found.push({ pos, level: Number(node.attrs.level), text: node.textContent.trim() });
    }
  });
  return found;
}

const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

/** Scroll to a heading and put the cursor at its start. */
export function goToHeading(editor: Editor, heading: string) {
  const target = headings(editor.state.doc).find((h) => same(h.text, heading));
  if (!target) return;
  editor.chain().focus().setTextSelection(target.pos + 1).run();
  (editor.view.nodeDOM(target.pos) as HTMLElement | null)?.scrollIntoView({ block: "center", behavior: "smooth" });
}

/**
 * Add an H2 (and an empty paragraph to write in) after the section `after`: before the
 * next heading of the same or a higher level. "the introduction" means before the first
 * H2; an unknown or empty `after` means the end of the page.
 */
export function addSection(editor: Editor, heading: string, after = "") {
  const doc = editor.state.doc;
  const all = headings(doc);
  let at = doc.content.size;
  if (same(after, "the introduction")) {
    at = all.find((h) => h.level >= 2)?.pos ?? at;
  } else if (after) {
    const index = all.findIndex((h) => same(h.text, after));
    const anchor = all[index];
    if (anchor) {
      const next = all.slice(index + 1).find((h) => h.level <= anchor.level);
      at = next?.pos ?? at;
    }
  }
  editor
    .chain()
    .focus()
    .insertContentAt(at, [
      { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: heading }] },
      { type: "paragraph" },
    ])
    .setTextSelection(at + heading.length + 3) // inside the new paragraph
    .run();
  (editor.view.nodeDOM(at) as HTMLElement | null)?.scrollIntoView({ block: "center", behavior: "smooth" });
}

/** Use `text` as the main heading: replace the first H1, or add one at the top. */
export function setMainHeading(editor: Editor, text: string) {
  const h1 = headings(editor.state.doc).find((h) => h.level === 1);
  const node = { type: "heading", attrs: { level: 1 }, content: [{ type: "text", text }] };
  if (h1) {
    const size = editor.state.doc.nodeAt(h1.pos)?.nodeSize ?? 0;
    editor.chain().focus().insertContentAt({ from: h1.pos, to: h1.pos + size }, node).run();
  } else {
    editor.chain().focus().insertContentAt(0, node).run();
  }
}

// --- The editor --------------------------------------------------------------------------

/**
 * `hintFor(heading)` is the brief's note on what to write under that heading; it's shown
 * in the empty paragraph below it.
 */
export function useDraftEditor(
  initialHtml: string,
  onChange: (html: string) => void,
  hintFor: (heading: string) => string | undefined,
): Editor | null {
  const changed = useRef(onChange);
  const hints = useRef(hintFor);
  useEffect(() => {
    changed.current = onChange;
    hints.current = hintFor;
  });

  const editor = useEditor({
    immediatelyRender: false, // rendered in the browser only, so server and browser agree
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
        code: false,
        codeBlock: false,
        link: { openOnClick: false, autolink: true },
      }),
      SectionHints.configure({ hintFor: (heading) => hints.current(heading) }),
      TermHighlight,
    ],
    content: initialHtml,
    editorProps: { attributes: { class: "prose-editor", "aria-label": "Draft" } },
    onUpdate: ({ editor }) => changed.current(editor.getHTML()),
  });
  return editor;
}

/** Redraw the hints, e.g. once the brief has loaded. */
export function refreshHints(editor: Editor) {
  editor.view.dispatch(editor.state.tr.setMeta("addToHistory", false));
}

export function DraftEditor({ editor }: { editor: Editor | null }) {
  return <EditorContent editor={editor} className="min-h-[60vh]" />;
}

// --- Toolbar -----------------------------------------------------------------------------

function ToolButton({
  label,
  active,
  disabled,
  onClick,
  children,
}: {
  label: string;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      disabled={disabled}
      onMouseDown={(e) => e.preventDefault()} // keep the editor's selection
      onClick={onClick}
      className={cn(
        "inline-flex size-7 items-center justify-center rounded text-muted hover:bg-surface-2 hover:text-foreground",
        "disabled:opacity-40 disabled:hover:bg-transparent",
        active && "bg-accent-soft text-accent hover:bg-accent-soft hover:text-accent",
      )}
    >
      {children}
    </button>
  );
}

export function Toolbar({ editor }: { editor: Editor | null }) {
  const state = useEditorState({
    editor,
    selector: ({ editor }) =>
      editor && {
        paragraph: editor.isActive("paragraph"),
        h1: editor.isActive("heading", { level: 1 }),
        h2: editor.isActive("heading", { level: 2 }),
        h3: editor.isActive("heading", { level: 3 }),
        bold: editor.isActive("bold"),
        italic: editor.isActive("italic"),
        bullets: editor.isActive("bulletList"),
        numbers: editor.isActive("orderedList"),
        quote: editor.isActive("blockquote"),
        link: editor.isActive("link"),
        undo: editor.can().undo(),
        redo: editor.can().redo(),
      },
  });
  if (!editor || !state) return <div className="h-10 border-b border-border" />;
  const chain = () => editor.chain().focus();

  function link() {
    if (!editor) return;
    if (editor.isActive("link")) {
      chain().unsetLink().run();
      return;
    }
    const href = window.prompt("Link to (web address)", "https://");
    if (href && href !== "https://") chain().extendMarkRange("link").setLink({ href }).run();
  }

  return (
    <div
      role="toolbar"
      aria-label="Formatting"
      className="sticky top-0 z-10 flex h-10 flex-wrap items-center gap-0.5 border-b border-border bg-background/95 px-2 backdrop-blur"
    >
      <ToolButton label="Paragraph" active={state.paragraph} onClick={() => chain().setParagraph().run()}>
        <Pilcrow className="size-3.5" />
      </ToolButton>
      <ToolButton label="Main heading (H1)" active={state.h1} onClick={() => chain().toggleHeading({ level: 1 }).run()}>
        <Heading1 className="size-4" />
      </ToolButton>
      <ToolButton label="Section heading (H2)" active={state.h2} onClick={() => chain().toggleHeading({ level: 2 }).run()}>
        <Heading2 className="size-4" />
      </ToolButton>
      <ToolButton label="Sub-heading (H3)" active={state.h3} onClick={() => chain().toggleHeading({ level: 3 }).run()}>
        <Heading3 className="size-4" />
      </ToolButton>
      <span className="mx-1 h-4 w-px bg-border" aria-hidden />
      <ToolButton label="Bold" active={state.bold} onClick={() => chain().toggleBold().run()}>
        <Bold className="size-3.5" />
      </ToolButton>
      <ToolButton label="Italic" active={state.italic} onClick={() => chain().toggleItalic().run()}>
        <Italic className="size-3.5" />
      </ToolButton>
      <ToolButton label="Link" active={state.link} onClick={link}>
        <Link2 className="size-3.5" />
      </ToolButton>
      <span className="mx-1 h-4 w-px bg-border" aria-hidden />
      <ToolButton label="Bullet list" active={state.bullets} onClick={() => chain().toggleBulletList().run()}>
        <List className="size-3.5" />
      </ToolButton>
      <ToolButton label="Numbered list" active={state.numbers} onClick={() => chain().toggleOrderedList().run()}>
        <ListOrdered className="size-3.5" />
      </ToolButton>
      <ToolButton label="Quote" active={state.quote} onClick={() => chain().toggleBlockquote().run()}>
        <Quote className="size-3.5" />
      </ToolButton>
      <span className="ml-auto" />
      <ToolButton label="Undo" disabled={!state.undo} onClick={() => chain().undo().run()}>
        <Undo2 className="size-3.5" />
      </ToolButton>
      <ToolButton label="Redo" disabled={!state.redo} onClick={() => chain().redo().run()}>
        <Redo2 className="size-3.5" />
      </ToolButton>
    </div>
  );
}
