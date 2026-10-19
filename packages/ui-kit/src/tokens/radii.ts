/** Corner-radius tokens. */
export const radii = { sm: 6, md: 10, lg: 12, xl: 16, pill: 999 } as const;
export type RadiusToken = keyof typeof radii;
