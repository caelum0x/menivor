/** `CaptionStyle` + preset registry (mirror of `style.py`). */

export interface CaptionStyle {
  font: string;
  size: number;
  primary_hex: string;
  highlight_hex: string;
  outline_hex: string;
  outline: number;
  shadow: number;
  alignment: number; // ASS numpad
  margin_v: number;
  bold: boolean;
  uppercase: boolean;
  words_per_group: number;
}

const HORMOZI: CaptionStyle = {
  font: "Montserrat Black",
  size: 120,
  primary_hex: "#FFFFFF",
  highlight_hex: "#FFD93D",
  outline_hex: "#000000",
  outline: 4,
  shadow: 2,
  alignment: 5,
  margin_v: 0,
  bold: true,
  uppercase: true,
  words_per_group: 2,
};

const PRESETS: Record<string, CaptionStyle> = {
  hormozi: HORMOZI,
  "karaoke-classic": {
    ...HORMOZI,
    font: "Arial",
    size: 90,
    highlight_hex: "#35D9FF",
    alignment: 2,
    margin_v: 120,
    uppercase: false,
    words_per_group: 4,
  },
  "minimal-top-label": {
    ...HORMOZI,
    font: "Helvetica",
    size: 64,
    highlight_hex: "#FFFFFF",
    outline: 2,
    shadow: 1,
    alignment: 8,
    margin_v: 120,
    bold: false,
    uppercase: false,
    words_per_group: 1,
  },
  "brainrot-popin": {
    ...HORMOZI,
    font: "Impact",
    size: 140,
    highlight_hex: "#39FF14",
    outline: 6,
    shadow: 0,
    alignment: 5,
    words_per_group: 2,
  },
};

export function getPreset(name: string): CaptionStyle {
  const s = PRESETS[name];
  if (!s) throw new Error(`unknown caption preset ${name}`);
  return s;
}

export function listPresets(): string[] {
  return Object.keys(PRESETS).sort();
}
