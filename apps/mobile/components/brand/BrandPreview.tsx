/**
 * BrandPreview — a small 9:16 mock reel frame showing where the watermark will
 * sit. Positions the uploaded logo (or a placeholder tile until one is
 * uploaded) in the chosen corner at the chosen opacity, so a creator can sanity
 * check the overlay before saving. Purely presentational.
 */

import { Image, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import { toDisplayUrl } from "@/src/shared/media";
import {
  DEFAULT_WATERMARK_POSITION,
  WATERMARK_POSITIONS,
  type WatermarkPosition,
} from "@/lib/types";

interface BrandPreviewProps {
  /** Presigned logo URL, or null/undefined to show the placeholder tile. */
  logoUrl?: string | null;
  position: WatermarkPosition | string;
  opacity: number;
  enabled: boolean;
}

/** Absolute inset per corner within the padded frame. */
const CORNER_STYLE: Record<WatermarkPosition, object> = {
  top_left: { top: 0, left: 0 },
  top_right: { top: 0, right: 0 },
  bottom_left: { bottom: 0, left: 0 },
  bottom_right: { bottom: 0, right: 0 },
};

function normalizePosition(value: WatermarkPosition | string): WatermarkPosition {
  return (WATERMARK_POSITIONS as readonly string[]).includes(value)
    ? (value as WatermarkPosition)
    : DEFAULT_WATERMARK_POSITION;
}

export function BrandPreview({
  logoUrl,
  position,
  opacity,
  enabled,
}: BrandPreviewProps) {
  const url = toDisplayUrl(logoUrl);
  const corner = CORNER_STYLE[normalizePosition(position)];
  // The overlay is only shown when the watermark is enabled AND a logo exists.
  const showOverlay = enabled;

  return (
    <View style={styles.wrap}>
      <View style={styles.frame}>
        <Text style={styles.frameLabel}>Preview</Text>

        {showOverlay ? (
          <View style={[styles.overlay, corner, { opacity }]}>
            {url ? (
              <Image
                source={{ uri: url }}
                style={styles.logo}
                resizeMode="contain"
                accessibilityLabel="Watermark logo preview"
              />
            ) : (
              <View style={styles.placeholder}>
                <Text style={styles.placeholderText}>LOGO</Text>
              </View>
            )}
          </View>
        ) : null}
      </View>
      {!enabled ? (
        <Text style={styles.caption}>Watermark disabled</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: "center", gap: 8 },
  frame: {
    width: 120,
    height: 213, // 9:16
    borderRadius: 12,
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    padding: 8,
    overflow: "hidden",
  },
  frameLabel: {
    color: colors.muted,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 1,
    alignSelf: "center",
  },
  overlay: { position: "absolute", margin: 8 },
  logo: { width: 44, height: 44 },
  placeholder: {
    width: 44,
    height: 24,
    borderRadius: 4,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  placeholderText: { color: colors.textPrimary, fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  caption: { color: colors.muted, fontSize: 11 },
});
