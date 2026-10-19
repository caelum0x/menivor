/**
 * Read-only preview of one design page, drawn with plain React Native views at
 * a scale that fits `maxWidth`. Mirrors the web renderer's geometry (layers
 * rotate around their centre, lines run through the vertical middle, images
 * cover/contain inside a rounded clip). Brand fonts are not bundled in the
 * app, so text uses the system face at the design's size and weight — the
 * exported PNG (rendered on the web) is the source of truth.
 */

import { memo } from "react";
import { Image, StyleSheet, Text, View, type ViewStyle } from "react-native";

import { colors } from "@/src/shared/theme";
import {
  designMediaSource,
  previewScale,
  type Layer,
  type Page,
} from "@/lib/design-studio";

export interface DesignPreviewProps {
  page: Page;
  width: number;
  height: number;
  maxWidth: number;
  maxHeight?: number;
  token?: string;
}

function frame(layer: Layer, s: number): ViewStyle {
  return {
    position: "absolute",
    left: layer.x * s,
    top: layer.y * s,
    width: layer.width * s,
    height: layer.height * s,
    opacity: layer.opacity,
    transform: layer.rotation ? [{ rotate: `${layer.rotation}deg` }] : undefined,
  };
}

function paint(value: string): string {
  return value === "transparent" || !value ? "transparent" : value;
}

function LayerView({ layer, s, token }: { layer: Layer; s: number; token?: string }) {
  if (layer.hidden) return null;
  const box = frame(layer, s);
  switch (layer.type) {
    case "text": {
      const p = layer.props;
      return (
        <View style={box} pointerEvents="none">
          <Text
            style={{
              color: p.color,
              fontSize: Math.max(1, p.fontSize * s),
              lineHeight: Math.max(1, p.fontSize * p.lineHeight * s),
              fontWeight: p.fontWeight >= 600 ? "700" : "400",
              fontStyle: p.italic ? "italic" : "normal",
              textAlign: p.align,
              letterSpacing: (p.letterSpacing ?? 0) * s,
              textTransform: p.uppercase ? "uppercase" : "none",
            }}
          >
            {p.text}
          </Text>
        </View>
      );
    }
    case "image":
      return (
        <View style={[box, { borderRadius: layer.props.radius * s, overflow: "hidden" }]}>
          <Image
            source={designMediaSource(layer.props.key, token)}
            style={StyleSheet.absoluteFill}
            resizeMode={layer.props.fit}
            accessibilityIgnoresInvertColors
          />
        </View>
      );
    case "rect":
    case "ellipse": {
      const p = layer.props;
      const radius =
        layer.type === "ellipse"
          ? Math.max(layer.width, layer.height) * s
          : (p.radius ?? 0) * s;
      return (
        <View
          style={[
            box,
            {
              backgroundColor: paint(p.fill),
              borderColor: paint(p.stroke),
              borderWidth: p.stroke && p.stroke !== "transparent" ? p.strokeWidth * s : 0,
              borderRadius: radius,
            },
          ]}
        />
      );
    }
    case "line": {
      const thickness = Math.max(1, layer.props.strokeWidth * s);
      return (
        <View style={box} pointerEvents="none">
          <View
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              top: (layer.height * s - thickness) / 2,
              height: thickness,
              borderRadius: thickness / 2,
              backgroundColor: layer.props.stroke,
            }}
          />
        </View>
      );
    }
    default:
      return null;
  }
}

function DesignPreviewImpl({ page, width, height, maxWidth, maxHeight, token }: DesignPreviewProps) {
  const s = previewScale(width, height, maxWidth, maxHeight);
  if (s <= 0) return null;
  return (
    <View
      style={[
        styles.page,
        { width: width * s, height: height * s, backgroundColor: page.background },
      ]}
      accessibilityRole="image"
      accessibilityLabel="Design preview"
    >
      {page.layers.map((layer) => (
        <LayerView key={layer.id} layer={layer} s={s} token={token} />
      ))}
    </View>
  );
}

export const DesignPreview = memo(DesignPreviewImpl);

const styles = StyleSheet.create({
  page: {
    overflow: "hidden",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
});
