/**
 * Render a design page to PNG in the browser (Canvas 2D). Uses the same text
 * wrapping as the editor. Images come from same-origin blob URLs (see
 * `fetchImageBlobUrl`) so `toDataURL` is never blocked by a tainted canvas.
 */

import { fontString, wrapText } from "./text-layout";
import type { Layer, Page } from "./types";

export type ImageSource = (key: string) => Promise<string>;

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("An image on the design could not be loaded."));
    img.src = src;
  });
}

function roundedRect(c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  const radius = Math.max(0, Math.min(r, w / 2, h / 2));
  c.beginPath();
  c.moveTo(x + radius, y);
  c.arcTo(x + w, y, x + w, y + h, radius);
  c.arcTo(x + w, y + h, x, y + h, radius);
  c.arcTo(x, y + h, x, y, radius);
  c.arcTo(x, y, x + w, y, radius);
  c.closePath();
}

function drawImageFit(c: CanvasRenderingContext2D, img: HTMLImageElement, l: Layer & { type: "image" }) {
  const { width: bw, height: bh } = l;
  const iw = img.naturalWidth || 1;
  const ih = img.naturalHeight || 1;
  const scale = l.props.fit === "cover" ? Math.max(bw / iw, bh / ih) : Math.min(bw / iw, bh / ih);
  const dw = iw * scale;
  const dh = ih * scale;
  c.save();
  roundedRect(c, 0, 0, bw, bh, l.props.radius);
  c.clip();
  c.drawImage(img, (bw - dw) / 2, (bh - dh) / 2, dw, dh);
  c.restore();
}

async function drawLayer(c: CanvasRenderingContext2D, l: Layer, images: Map<string, HTMLImageElement>) {
  if (l.hidden) return;
  c.save();
  c.globalAlpha = l.opacity;
  c.translate(l.x + l.width / 2, l.y + l.height / 2);
  c.rotate((l.rotation * Math.PI) / 180);
  c.translate(-l.width / 2, -l.height / 2);
  switch (l.type) {
    case "rect": {
      roundedRect(c, 0, 0, l.width, l.height, l.props.radius ?? 0);
      if (l.props.fill !== "transparent") {
        c.fillStyle = l.props.fill;
        c.fill();
      }
      if (l.props.stroke && l.props.strokeWidth > 0 && l.props.stroke !== "transparent") {
        // Inset stroke, matching the editor's inset border.
        const sw = l.props.strokeWidth;
        roundedRect(c, sw / 2, sw / 2, l.width - sw, l.height - sw, Math.max(0, (l.props.radius ?? 0) - sw / 2));
        c.lineWidth = sw;
        c.strokeStyle = l.props.stroke;
        c.stroke();
      }
      break;
    }
    case "ellipse": {
      c.beginPath();
      c.ellipse(l.width / 2, l.height / 2, l.width / 2, l.height / 2, 0, 0, Math.PI * 2);
      if (l.props.fill !== "transparent") {
        c.fillStyle = l.props.fill;
        c.fill();
      }
      if (l.props.stroke && l.props.strokeWidth > 0 && l.props.stroke !== "transparent") {
        const sw = l.props.strokeWidth;
        c.beginPath();
        c.ellipse(l.width / 2, l.height / 2, Math.max(0, l.width / 2 - sw / 2), Math.max(0, l.height / 2 - sw / 2), 0, 0, Math.PI * 2);
        c.lineWidth = sw;
        c.strokeStyle = l.props.stroke;
        c.stroke();
      }
      break;
    }
    case "line": {
      c.beginPath();
      c.moveTo(0, l.height / 2);
      c.lineTo(l.width, l.height / 2);
      c.lineWidth = l.props.strokeWidth;
      c.strokeStyle = l.props.stroke;
      c.lineCap = "round";
      c.stroke();
      break;
    }
    case "image": {
      const img = images.get(l.props.key);
      if (img) drawImageFit(c, img, l);
      break;
    }
    case "text": {
      const p = l.props;
      c.font = fontString(p);
      c.fillStyle = p.color;
      c.textBaseline = "top";
      c.textAlign = p.align;
      if ("letterSpacing" in c) {
        (c as CanvasRenderingContext2D & { letterSpacing: string }).letterSpacing = `${p.letterSpacing ?? 0}px`;
      }
      const lines = wrapText(p, l.width, c);
      const lineH = p.fontSize * p.lineHeight;
      const x = p.align === "center" ? l.width / 2 : p.align === "right" ? l.width : 0;
      lines.forEach((line, i) => {
        c.fillText(line, x, i * lineH + (lineH - p.fontSize) / 2);
      });
      break;
    }
  }
  c.restore();
}

/** Render one page to a PNG data URL at full size. */
export async function renderPageToPng(page: Page, width: number, height: number, imageSource: ImageSource): Promise<string> {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const c = canvas.getContext("2d");
  if (!c) throw new Error("Your browser cannot render the design (no canvas support).");
  const keys = [...new Set(page.layers.filter((l) => l.type === "image" && !l.hidden).map((l) => (l as Layer & { type: "image" }).props.key))];
  const images = new Map<string, HTMLImageElement>();
  await Promise.all(
    keys.map(async (key) => {
      images.set(key, await loadImage(await imageSource(key)));
    }),
  );
  c.fillStyle = page.background;
  c.fillRect(0, 0, width, height);
  for (const layer of page.layers) await drawLayer(c, layer, images);
  return canvas.toDataURL("image/png");
}
