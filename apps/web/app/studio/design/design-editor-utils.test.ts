import { describe, expect, it } from "vitest";

import {
  addPage,
  duplicateLayer,
  moveLayerOrder,
  removePage,
  shapeLayer,
  updateLayer,
} from "@/components/design/canvas-ops";
import { snapBox } from "@/components/design/snap";
import type { Canvas } from "@/components/design/types";

const base = (): Canvas => ({
  version: 1,
  pages: [{ background: "#ffffff", layers: [shapeLayer("rect", 1000, 1000, "#ff0000"), shapeLayer("ellipse", 1000, 1000, "#00ff00")] }],
});

describe("snapBox", () => {
  it("snaps a box centre to the page centre and reports the guide", () => {
    const r = snapBox({ x: 395, y: 10, width: 200, height: 100 }, [], { width: 1000, height: 1000 }, 8);
    expect(r.x).toBe(400);
    expect(r.guidesX).toEqual([500]);
    expect(r.y).toBe(10);
  });

  it("snaps to another layer's edge and leaves far boxes alone", () => {
    const other = { x: 600, y: 600, width: 100, height: 100 };
    expect(snapBox({ x: 703, y: 300, width: 50, height: 50 }, [other], { width: 1000, height: 1000 }, 5).x).toBe(700);
    expect(snapBox({ x: 720, y: 300, width: 50, height: 50 }, [other], { width: 1000, height: 1000 }, 5).guidesX).toEqual([]);
  });
});

describe("canvas ops are immutable", () => {
  it("updates one layer without touching the original", () => {
    const c = base();
    const id = c.pages[0]!.layers[0]!.id;
    const next = updateLayer(c, 0, id, { x: 5 });
    expect(next.pages[0]!.layers[0]!.x).toBe(5);
    expect(c.pages[0]!.layers[0]!.x).not.toBe(5);
  });

  it("duplicates, reorders and manages pages", () => {
    const c = base();
    const first = c.pages[0]!.layers[0]!.id;
    const dup = duplicateLayer(c, 0, first);
    expect(dup.canvas.pages[0]!.layers).toHaveLength(3);
    const top = moveLayerOrder(c, 0, first, "top");
    expect(top.pages[0]!.layers.at(-1)!.id).toBe(first);
    const two = addPage(c, 0, c.pages[0]);
    expect(two.pages).toHaveLength(2);
    expect(two.pages[1]!.layers[0]!.id).not.toBe(first);
    expect(removePage(two, 1).pages).toHaveLength(1);
    expect(removePage(c, 0).pages).toHaveLength(1);
  });
});
