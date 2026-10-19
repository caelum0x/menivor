"use client";

import * as React from "react";

import { fetchImageBlobUrl } from "./api";
import { displayText, wrapText } from "./text-layout";
import type { Layer, Page } from "./types";

const blobCache = new Map<string, Promise<string>>();

/** Same-origin blob URL for an owned image key (cached for the session). */
export function imageUrlFor(key: string, getOptions: () => Promise<{ token?: string }>): Promise<string> {
  let hit = blobCache.get(key);
  if (!hit) {
    hit = getOptions().then((opts) => fetchImageBlobUrl(key, opts));
    hit.catch(() => blobCache.delete(key));
    blobCache.set(key, hit);
  }
  return hit;
}

export function useImageUrls(keys: string[], getOptions: () => Promise<{ token?: string }>): Record<string, string> {
  const [urls, setUrls] = React.useState<Record<string, string>>({});
  const joined = [...new Set(keys)].sort().join("|");
  React.useEffect(() => {
    let alive = true;
    for (const key of joined ? joined.split("|") : []) {
      imageUrlFor(key, getOptions)
        .then((url) => alive && setUrls((u) => (u[key] === url ? u : { ...u, [key]: url })))
        .catch(() => undefined);
    }
    return () => {
      alive = false;
    };
  }, [joined, getOptions]);
  return urls;
}

export function imageKeys(pages: Page[]): string[] {
  return pages.flatMap((p) => p.layers.flatMap((l) => (l.type === "image" ? [l.props.key] : [])));
}

function LayerBody({ layer, imageUrl, fontsVersion }: { layer: Layer; imageUrl?: string; fontsVersion: number }) {
  switch (layer.type) {
    case "rect":
      return (
        <div
          className="h-full w-full"
          style={{
            background: layer.props.fill === "transparent" ? "transparent" : layer.props.fill,
            borderRadius: layer.props.radius ?? 0,
            boxShadow:
              layer.props.stroke && layer.props.strokeWidth > 0
                ? `inset 0 0 0 ${layer.props.strokeWidth}px ${layer.props.stroke}`
                : undefined,
          }}
        />
      );
    case "ellipse":
      return (
        <div
          className="h-full w-full rounded-[50%]"
          style={{
            background: layer.props.fill === "transparent" ? "transparent" : layer.props.fill,
            boxShadow:
              layer.props.stroke && layer.props.strokeWidth > 0
                ? `inset 0 0 0 ${layer.props.strokeWidth}px ${layer.props.stroke}`
                : undefined,
          }}
        />
      );
    case "line":
      return (
        <div className="flex h-full w-full items-center">
          <div
            className="w-full rounded-full"
            style={{ height: layer.props.strokeWidth, background: layer.props.stroke }}
          />
        </div>
      );
    case "image":
      return imageUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={imageUrl}
          alt=""
          draggable={false}
          className="pointer-events-none h-full w-full select-none"
          style={{ objectFit: layer.props.fit, borderRadius: layer.props.radius }}
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center bg-black/10 text-[24px] text-black/50">
          Loading image
        </div>
      );
    case "text": {
      const p = layer.props;
      // fontsVersion forces a re-wrap once web fonts finish loading.
      void fontsVersion;
      const lines = wrapText(p, layer.width);
      return (
        <div
          className="h-full w-full whitespace-pre"
          style={{
            fontFamily: `"${p.fontFamily}", system-ui, sans-serif`,
            fontSize: p.fontSize,
            fontWeight: p.fontWeight,
            fontStyle: p.italic ? "italic" : "normal",
            color: p.color,
            textAlign: p.align,
            lineHeight: `${p.fontSize * p.lineHeight}px`,
            letterSpacing: p.letterSpacing ? `${p.letterSpacing}px` : undefined,
          }}
          aria-label={displayText(p)}
        >
          {lines.map((line, i) => (
            <div key={i}>{line || " "}</div>
          ))}
        </div>
      );
    }
  }
}

export interface PageViewProps {
  page: Page;
  width: number;
  height: number;
  scale: number;
  imageUrls: Record<string, string>;
  fontsVersion?: number;
  selectedId?: string | null;
  onLayerPointerDown?: (e: React.PointerEvent, layer: Layer) => void;
  onBackgroundPointerDown?: (e: React.PointerEvent) => void;
  overlay?: React.ReactNode;
}

/** Renders one page at full size, scaled with a CSS transform (page units = pixels). */
export function PageView({
  page,
  width,
  height,
  scale,
  imageUrls,
  fontsVersion = 0,
  selectedId,
  onLayerPointerDown,
  onBackgroundPointerDown,
  overlay,
}: PageViewProps) {
  return (
    <div className="relative overflow-hidden" style={{ width: width * scale, height: height * scale }}>
      <div
        className="absolute left-0 top-0 origin-top-left"
        style={{ width, height, transform: `scale(${scale})`, background: page.background }}
        onPointerDown={onBackgroundPointerDown}
      >
        {page.layers.map((layer) =>
          layer.hidden ? null : (
            <div
              key={layer.id}
              data-layer-id={layer.id}
              className={onLayerPointerDown && !layer.locked ? "absolute cursor-move" : "absolute"}
              style={{
                left: layer.x,
                top: layer.y,
                width: layer.width,
                height: layer.height,
                opacity: layer.opacity,
                transform: layer.rotation ? `rotate(${layer.rotation}deg)` : undefined,
                outline: selectedId === layer.id ? `${2 / scale}px solid #3b82f6` : undefined,
              }}
              onPointerDown={onLayerPointerDown ? (e) => onLayerPointerDown(e, layer) : undefined}
            >
              <LayerBody
                layer={layer}
                imageUrl={layer.type === "image" ? imageUrls[layer.props.key] : undefined}
                fontsVersion={fontsVersion}
              />
            </div>
          ),
        )}
        {overlay}
      </div>
    </div>
  );
}
