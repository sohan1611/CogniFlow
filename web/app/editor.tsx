"use client";

import { closeBrackets } from "@codemirror/autocomplete";
import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
} from "@codemirror/commands";
import { python } from "@codemirror/lang-python";
import { bracketMatching, indentUnit } from "@codemirror/language";
import { Annotation, Compartment, EditorState } from "@codemirror/state";
import {
  EditorView,
  highlightActiveLine,
  keymap,
  lineNumbers,
} from "@codemirror/view";
import { useEffect, useMemo, useRef } from "react";

const externalValue = Annotation.define<boolean>();
const editorDefaultKeymap = defaultKeymap.filter((binding) => binding.key !== "Escape");

function editorTheme(minHeight: number) {
  return EditorView.theme({
    "&": {
      width: "100%",
      maxWidth: "100%",
      minHeight: `${minHeight}px`,
      color: "var(--ink)",
      backgroundColor: "var(--editor-bg)",
      border: "1px solid var(--editor-border)",
      borderRadius: "var(--r-sm)",
      overflow: "hidden",
    },
    "&.cm-focused": {
      outline: "2px solid var(--focus)",
      outlineOffset: "2px",
    },
    ".cm-scroller": {
      minHeight: `${minHeight}px`,
      overflow: "auto",
      fontFamily: "ui-monospace, Cascadia Code, Consolas, monospace",
      fontSize: "16px",
      lineHeight: "1.55",
    },
    ".cm-content": {
      minHeight: `${minHeight}px`,
      padding: "12px 0",
      caretColor: "var(--ink)",
    },
    ".cm-line": {
      padding: "0 12px",
      overflowWrap: "anywhere",
    },
    ".cm-gutters": {
      backgroundColor: "var(--editor-gutter)",
      color: "var(--ink-3)",
      borderRight: "1px solid var(--editor-border)",
    },
    ".cm-activeLine, .cm-activeLineGutter": {
      backgroundColor: "var(--editor-active)",
    },
    ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
      backgroundColor: "var(--editor-selection)",
    },
    ".cm-matchingBracket": {
      backgroundColor: "var(--brand-soft)",
      color: "var(--ink)",
    },
    ".cm-nonmatchingBracket": {
      backgroundColor: "var(--danger)",
      color: "var(--danger-ink)",
    },
  });
}

export function CodeEditor({
  value,
  onChange,
  ariaLabel,
  minHeight = 220,
}: {
  value: string;
  onChange: (next: string) => void;
  ariaLabel: string;
  minHeight?: number;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  const attributes = useMemo(() => new Compartment(), []);
  const themed = useMemo(() => new Compartment(), []);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  useEffect(() => {
    if (!hostRef.current || viewRef.current) return;

    const state = EditorState.create({
      doc: value,
      extensions: [
        python(),
        history(),
        lineNumbers(),
        bracketMatching(),
        closeBrackets(),
        highlightActiveLine(),
        EditorView.lineWrapping,
        EditorState.tabSize.of(4),
        indentUnit.of("    "),
        attributes.of(
          EditorView.contentAttributes.of({
            "aria-label": ariaLabel,
            spellcheck: "false",
          }),
        ),
        themed.of(editorTheme(minHeight)),
        EditorView.updateListener.of((update) => {
          if (!update.docChanged) return;
          const cameFromProps = update.transactions.some((transaction) =>
            transaction.annotation(externalValue),
          );
          if (!cameFromProps) onChangeRef.current(update.state.doc.toString());
        }),
        keymap.of([...editorDefaultKeymap, ...historyKeymap, indentWithTab]),
      ],
    });

    viewRef.current = new EditorView({
      state,
      parent: hostRef.current,
    });

    return () => {
      viewRef.current?.destroy();
      viewRef.current = null;
    };
  }, [attributes, themed]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (value === current) return;
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: value },
      annotations: externalValue.of(true),
    });
  }, [value]);

  useEffect(() => {
    viewRef.current?.dispatch({
      effects: attributes.reconfigure(
        EditorView.contentAttributes.of({
          "aria-label": ariaLabel,
          spellcheck: "false",
        }),
      ),
    });
  }, [ariaLabel, attributes]);

  useEffect(() => {
    viewRef.current?.dispatch({
      effects: themed.reconfigure(editorTheme(minHeight)),
    });
  }, [minHeight, themed]);

  return (
    <div className="code-editor">
      <div ref={hostRef} />
      <p className="editor-hint">Tab indents · Esc then Tab to leave</p>
    </div>
  );
}
