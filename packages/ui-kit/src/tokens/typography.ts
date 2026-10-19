/** Type scale (px) + weights. */
export const fontSizes = { xs: 11, sm: 13, md: 15, lg: 18, xl: 22, xxl: 28, display: 34 } as const;
export const fontWeights = { regular: "400", medium: "600", bold: "700", black: "800" } as const;
export type FontSizeToken = keyof typeof fontSizes;
export type FontWeightToken = keyof typeof fontWeights;
