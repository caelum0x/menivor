"use client";

import * as React from "react";
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  ArrowDown,
  ArrowUp,
  Bold,
  Copy as CopyIcon,
  Italic,
  Lock,
  Trash2,
  Unlock,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import type { Layer } from "./types";

const HEX = /^#[0-9a-fA-F]{6}$/;
const COMMON_FONTS = ["Inter", "Poppins", "Montserrat", "Roboto", "Playfair Display", "Lora", "Oswald", "DM Sans"];

export interface InspectorProps {
  layer: Layer;
  swatches: string[];
  brandFonts: string[];
  textRef?: React.Ref<HTMLTextAreaElement>;
  /** `commit=false` while typing into a number/colour field keeps one undo step per edit. */
  onChange: (patch: Partial<Layer>) => void;
  onProps: (props: Record<string, unknown>) => void;
  onDelete: () => void;
  onDuplicate: () => void;
  onOrder: (dir: "up" | "down" | "top" | "bottom") => void;
}

function Num({ label, value, onChange, step = 1, min, max }: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
  min?: number;
  max?: number;
}) {
  const id = React.useId();
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </Label>
      <Input
        id={id}
        type="number"
        className="h-8"
        value={Number.isFinite(value) ? Math.round(value * 100) / 100 : 0}
        step={step}
        min={min}
        max={max}
        onChange={(e) => {
          const v = Number(e.target.value);
          if (Number.isFinite(v)) onChange(v);
        }}
      />
    </div>
  );
}

export function ColorField({ label, value, swatches, onChange, allowTransparent = false }: {
  label: string;
  value: string;
  swatches: string[];
  onChange: (v: string) => void;
  allowTransparent?: boolean;
}) {
  const id = React.useId();
  const [draft, setDraft] = React.useState(value);
  React.useEffect(() => setDraft(value), [value]);
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </Label>
      <div className="flex items-center gap-2">
        <input
          type="color"
          aria-label={`${label} picker`}
          className="h-8 w-10 cursor-pointer rounded border bg-transparent"
          value={HEX.test(value) ? value : "#ffffff"}
          onChange={(e) => onChange(e.target.value)}
        />
        <Input
          id={id}
          className="h-8 font-mono text-xs"
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            if (HEX.test(e.target.value) || (allowTransparent && e.target.value === "transparent")) onChange(e.target.value.toLowerCase());
          }}
        />
      </div>
      {swatches.length || allowTransparent ? (
        <div className="flex flex-wrap gap-1">
          {swatches.map((c) => (
            <button
              key={c}
              type="button"
              title={c}
              aria-label={`Use ${c}`}
              className={cn("size-6 rounded border", value === c && "ring-2 ring-primary")}
              style={{ background: c }}
              onClick={() => onChange(c)}
            />
          ))}
          {allowTransparent ? (
            <button
              type="button"
              className={cn("h-6 rounded border px-2 text-[10px]", value === "transparent" && "ring-2 ring-primary")}
              onClick={() => onChange("transparent")}
            >
              None
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function Toggle({ active, onClick, label, children }: { active: boolean; onClick: () => void; label: string; children: React.ReactNode }) {
  return (
    <Button type="button" size="icon" variant={active ? "secondary" : "ghost"} aria-pressed={active} aria-label={label} title={label} className="h-8 w-8" onClick={onClick}>
      {children}
    </Button>
  );
}

/** Properties of the selected layer. */
export function Inspector({ layer, swatches, brandFonts, textRef, onChange, onProps, onDelete, onDuplicate, onOrder }: InspectorProps) {
  const fonts = [...new Set([...brandFonts, ...COMMON_FONTS])];
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <Input
          aria-label="Layer name"
          className="h-8"
          value={layer.name}
          maxLength={60}
          onChange={(e) => onChange({ name: e.target.value })}
        />
        <Toggle active={!!layer.locked} label={layer.locked ? "Unlock layer" : "Lock layer"} onClick={() => onChange({ locked: !layer.locked })}>
          {layer.locked ? <Lock aria-hidden /> : <Unlock aria-hidden />}
        </Toggle>
      </div>

      {layer.type === "text" ? (
        <div className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="layer-text" className="text-xs text-muted-foreground">
              Text
            </Label>
            <Textarea
              id="layer-text"
              ref={textRef}
              rows={3}
              maxLength={600}
              value={layer.props.text}
              onChange={(e) => onProps({ text: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label htmlFor="layer-font" className="text-xs text-muted-foreground">
                Font
              </Label>
              <Select id="layer-font" className="h-8 py-1" value={layer.props.fontFamily} onChange={(e) => onProps({ fontFamily: e.target.value })}>
                {fonts.map((f) => (
                  <option key={f} value={f}>
                    {f}
                    {brandFonts.includes(f) ? " (brand)" : ""}
                  </option>
                ))}
              </Select>
            </div>
            <Num label="Size" value={layer.props.fontSize} min={6} max={800} onChange={(v) => onProps({ fontSize: Math.max(6, Math.min(800, v)) })} />
          </div>
          <div className="flex flex-wrap items-center gap-1">
            <Toggle active={layer.props.fontWeight === 700} label="Bold" onClick={() => onProps({ fontWeight: layer.props.fontWeight === 700 ? 400 : 700 })}>
              <Bold aria-hidden />
            </Toggle>
            <Toggle active={!!layer.props.italic} label="Italic" onClick={() => onProps({ italic: !layer.props.italic })}>
              <Italic aria-hidden />
            </Toggle>
            <Toggle active={layer.props.align === "left"} label="Align left" onClick={() => onProps({ align: "left" })}>
              <AlignLeft aria-hidden />
            </Toggle>
            <Toggle active={layer.props.align === "center"} label="Align centre" onClick={() => onProps({ align: "center" })}>
              <AlignCenter aria-hidden />
            </Toggle>
            <Toggle active={layer.props.align === "right"} label="Align right" onClick={() => onProps({ align: "right" })}>
              <AlignRight aria-hidden />
            </Toggle>
            <Button type="button" size="sm" variant={layer.props.uppercase ? "secondary" : "ghost"} aria-pressed={!!layer.props.uppercase} onClick={() => onProps({ uppercase: !layer.props.uppercase })}>
              Caps
            </Button>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Num label="Line height" step={0.05} value={layer.props.lineHeight} onChange={(v) => onProps({ lineHeight: Math.max(0.8, Math.min(3, v)) })} />
            <Num label="Letter spacing" value={layer.props.letterSpacing ?? 0} onChange={(v) => onProps({ letterSpacing: Math.max(-20, Math.min(100, v)) })} />
          </div>
          <ColorField label="Colour" value={layer.props.color} swatches={swatches} onChange={(v) => onProps({ color: v })} />
        </div>
      ) : null}

      {layer.type === "rect" || layer.type === "ellipse" ? (
        <div className="space-y-3">
          <ColorField label="Fill" value={layer.props.fill} swatches={swatches} allowTransparent onChange={(v) => onProps({ fill: v })} />
          <ColorField label="Border" value={layer.props.stroke || "transparent"} swatches={swatches} allowTransparent onChange={(v) => onProps({ stroke: v === "transparent" ? "" : v })} />
          <div className="grid grid-cols-2 gap-2">
            <Num label="Border width" min={0} max={200} value={layer.props.strokeWidth} onChange={(v) => onProps({ strokeWidth: Math.max(0, Math.min(200, v)) })} />
            {layer.type === "rect" ? (
              <Num label="Corner radius" min={0} value={layer.props.radius ?? 0} onChange={(v) => onProps({ radius: Math.max(0, v) })} />
            ) : null}
          </div>
        </div>
      ) : null}

      {layer.type === "line" ? (
        <div className="space-y-3">
          <ColorField label="Colour" value={layer.props.stroke} swatches={swatches} onChange={(v) => onProps({ stroke: v })} />
          <Num label="Thickness" min={1} max={200} value={layer.props.strokeWidth} onChange={(v) => onProps({ strokeWidth: Math.max(1, Math.min(200, v)) })} />
        </div>
      ) : null}

      {layer.type === "image" ? (
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <Label htmlFor="layer-fit" className="text-xs text-muted-foreground">
              Fit
            </Label>
            <Select id="layer-fit" className="h-8 py-1" value={layer.props.fit} onChange={(e) => onProps({ fit: e.target.value })}>
              <option value="cover">Fill the box</option>
              <option value="contain">Show whole image</option>
            </Select>
          </div>
          <Num label="Corner radius" min={0} value={layer.props.radius} onChange={(v) => onProps({ radius: Math.max(0, v) })} />
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-2">
        <Num label="X" value={layer.x} onChange={(v) => onChange({ x: v })} />
        <Num label="Y" value={layer.y} onChange={(v) => onChange({ y: v })} />
        <Num label="Width" min={1} value={layer.width} onChange={(v) => onChange({ width: Math.max(1, v) })} />
        <Num label="Height" min={1} value={layer.height} onChange={(v) => onChange({ height: Math.max(1, v) })} />
        <Num label="Rotation" min={-360} max={360} value={layer.rotation} onChange={(v) => onChange({ rotation: Math.max(-360, Math.min(360, v)) })} />
        <Num label="Opacity %" min={0} max={100} value={Math.round(layer.opacity * 100)} onChange={(v) => onChange({ opacity: Math.max(0, Math.min(100, v)) / 100 })} />
      </div>

      <div className="flex flex-wrap gap-1">
        <Button type="button" size="sm" variant="ghost" onClick={() => onOrder("up")} title="Bring forward">
          <ArrowUp aria-hidden /> Forward
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => onOrder("down")} title="Send backward">
          <ArrowDown aria-hidden /> Back
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDuplicate}>
          <CopyIcon aria-hidden /> Duplicate
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDelete}>
          <Trash2 aria-hidden /> Delete
        </Button>
      </div>
    </div>
  );
}
