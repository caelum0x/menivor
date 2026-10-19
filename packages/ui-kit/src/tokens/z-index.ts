/** Stacking order tokens. */
export const zIndex = { base: 0, dropdown: 100, sticky: 200, overlay: 900, modal: 1000, toast: 1100 } as const;
export type ZIndexToken = keyof typeof zIndex;
