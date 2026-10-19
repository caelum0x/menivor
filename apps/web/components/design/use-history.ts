"use client";

import * as React from "react";

const LIMIT = 100;

interface HistoryState<T> {
  past: T[];
  present: T;
  future: T[];
}

/**
 * Immutable undo/redo stack. `set(next, { merge: true })` replaces the present
 * without a new undo step (used while dragging so one drag = one step).
 */
export function useHistory<T>(initial: T) {
  const [state, setState] = React.useState<HistoryState<T>>({ past: [], present: initial, future: [] });

  const set = React.useCallback((next: T | ((prev: T) => T), opts?: { merge?: boolean }) => {
    setState((s) => {
      const value = typeof next === "function" ? (next as (prev: T) => T)(s.present) : next;
      if (Object.is(value, s.present)) return s;
      if (opts?.merge) return { ...s, present: value };
      return { past: [...s.past, s.present].slice(-LIMIT), present: value, future: [] };
    });
  }, []);

  /** Mark the current present as a checkpoint (call at drag start). */
  const checkpoint = React.useCallback(() => {
    setState((s) => ({ past: [...s.past, s.present].slice(-LIMIT), present: s.present, future: [] }));
  }, []);

  const undo = React.useCallback(() => {
    setState((s) => {
      const prev = s.past[s.past.length - 1];
      if (prev === undefined) return s;
      return { past: s.past.slice(0, -1), present: prev, future: [s.present, ...s.future] };
    });
  }, []);

  const redo = React.useCallback(() => {
    setState((s) => {
      const next = s.future[0];
      if (next === undefined) return s;
      return { past: [...s.past, s.present], present: next, future: s.future.slice(1) };
    });
  }, []);

  const reset = React.useCallback((value: T) => setState({ past: [], present: value, future: [] }), []);

  return {
    value: state.present,
    set,
    checkpoint,
    undo,
    redo,
    reset,
    canUndo: state.past.length > 0,
    canRedo: state.future.length > 0,
  };
}
