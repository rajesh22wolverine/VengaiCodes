// ─── Commit-on-blur text input for the schema editor ───
//
// Table and field names are committed when editing ends (blur / the
// keyboard's submit key), not per keystroke: a rename carries every
// reference along with it (spec, foreign keys, indexes, seed rows, check
// expressions), and half-typed names ("pri", "pric"…) would otherwise
// collide with other fields or briefly drop a reference. Same rule as the
// desktop editor's CommitInput.
//
// The phone-specific catch: with keyboardShouldPersistTaps="handled" a
// tap on Save goes straight to Save while the name input keeps focus and
// never blurs, and on Android the keyboard can be hidden with the back
// button while the input stays focused. Either way the rename would be
// silently left out of what gets saved. So every input with an
// uncommitted edit registers a flush function in PendingEditsContext,
// and the screen calls flushAll() before it saves or validates.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { TextInput, TextInputProps } from "react-native";

interface PendingEditsRegistry {
  /** `flush` commits the edit and returns false if it was refused. */
  register: (owner: object, flush: () => boolean) => void;
  unregister: (owner: object) => void;
}

export const PendingEditsContext = createContext<PendingEditsRegistry | null>(null);

/** Owned by the screen: the registry to provide, and flushAll() to call
 *  before reading the draft for a save or a validation. flushAll() is
 *  false when any edit was refused (a name clash — the input already put
 *  the old name back and the refusal explained itself), so a save can
 *  stop instead of storing something the user didn't mean. */
export function usePendingEdits(): { registry: PendingEditsRegistry; flushAll: () => boolean } {
  const flushes = useRef(new Map<object, () => boolean>());
  const registry = useMemo<PendingEditsRegistry>(
    () => ({
      register: (owner, flush) => {
        flushes.current.set(owner, flush);
      },
      unregister: (owner) => {
        flushes.current.delete(owner);
      },
    }),
    []
  );
  const flushAll = useCallback(() => {
    let allAccepted = true;
    // Copied first: each flush unregisters itself while we iterate.
    for (const flush of [...flushes.current.values()]) {
      if (!flush()) allAccepted = false;
    }
    return allAccepted;
  }, []);
  return { registry, flushAll };
}

type CommitTextInputProps = Omit<TextInputProps, "value" | "onChangeText" | "onBlur" | "onSubmitEditing"> & {
  value: string;
  /** Returns false to reject the text (the caller explains why). */
  onCommit: (next: string) => boolean;
  /** "Add field" mode: empty the input after a successful commit, and
   *  keep rejected text so it can be corrected rather than retyped. */
  clearOnCommit?: boolean;
};

export default function CommitTextInput({ value, onCommit, clearOnCommit, ...inputProps }: CommitTextInputProps) {
  const pending = useContext(PendingEditsContext);
  const [text, setText] = useState(value);
  const owner = useRef({}).current;
  // Refs, so a flush registered several renders ago still sees the latest
  // typed text, the latest saved value and the latest onCommit (whose
  // table/field index may have moved since).
  const textRef = useRef(value);
  const valueRef = useRef(value);
  const onCommitRef = useRef(onCommit);
  onCommitRef.current = onCommit;
  const mounted = useRef(true);

  useEffect(() => {
    valueRef.current = value;
    textRef.current = value;
    setText(value);
    pending?.unregister(owner);
  }, [value, pending, owner]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      // A row removed mid-edit takes its unfinished edit with it.
      mounted.current = false;
      pending?.unregister(owner);
    };
  }, [pending, owner]);

  const commit = useCallback((): boolean => {
    pending?.unregister(owner);
    if (!mounted.current) return true;
    const next = textRef.current;
    if (next === valueRef.current) return true;
    if (onCommitRef.current(next)) {
      if (clearOnCommit) {
        textRef.current = "";
        setText("");
      } else {
        // Until the new value arrives as a prop, don't commit it twice.
        valueRef.current = next;
      }
      return true;
    }
    if (!clearOnCommit) {
      textRef.current = valueRef.current;
      setText(valueRef.current);
    }
    return false;
  }, [pending, owner, clearOnCommit]);

  const onChangeText = (next: string) => {
    textRef.current = next;
    setText(next);
    if (next !== valueRef.current) pending?.register(owner, commit);
    else pending?.unregister(owner);
  };

  return (
    <TextInput
      autoCapitalize="none"
      autoCorrect={false}
      {...inputProps}
      value={text}
      onChangeText={onChangeText}
      onBlur={commit}
      onSubmitEditing={commit}
    />
  );
}
