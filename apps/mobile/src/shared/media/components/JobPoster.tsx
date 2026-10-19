import { useState } from "react";
import {
  Image,
  StyleSheet,
  View,
  type ImageStyle,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { ReelArt } from "@/src/ui/menivor/ReelArt";

/**
 * Shared signed-media poster frame, filling its (caller-sized) box. Falls
 * back to a film-strip placeholder when no poster URL is available or the image
 * fails to load. The parent controls dimensions via `style`.
 */

export interface JobPosterProps {
  /** Absolute poster image URL (see `lib/job-media.ts`), or undefined. */
  posterUrl?: string;
  /** Sizing/aspect style for the image (and the placeholder box). */
  style?: StyleProp<ImageStyle>;
  /** Accessibility label for the image. */
  accessibilityLabel?: string;
  /** Stable seed (job id) for the code-drawn frame shown before a poster exists. */
  seed?: string;
  /** Niche of a seeded demo project; draws its caption line on the frame. */
  niche?: string;
}

export function JobPoster({
  posterUrl,
  style,
  accessibilityLabel = "Reel poster",
  seed,
  niche,
}: Readonly<JobPosterProps>) {
  const [errored, setErrored] = useState(false);

  if ((!posterUrl || errored) && seed) {
    // Original code-drawn frame (no stock art). Real jobs get the abstract
    // scene only; captions are drawn just for seeded demo projects.
    return (
      <ReelArt
        seed={seed}
        niche={niche}
        showText={Boolean(niche)}
        style={style as StyleProp<ViewStyle>}
        accessibilityLabel={accessibilityLabel}
      />
    );
  }

  if (!posterUrl || errored) {
    return (
      <View style={[styles.placeholder, style as StyleProp<ViewStyle>]}>
        <View style={styles.placeholderFrame}>
          <View style={styles.placeholderLine} />
          <View style={[styles.placeholderLine, styles.placeholderLineShort]} />
        </View>
      </View>
    );
  }

  return (
    <Image
      source={{ uri: posterUrl }}
      style={[styles.image, style]}
      resizeMode="cover"
      accessibilityLabel={accessibilityLabel}
      onError={() => setErrored(true)}
    />
  );
}

const styles = StyleSheet.create({
  image: { backgroundColor: "#000000" },
  placeholder: {
    backgroundColor: "#1a1a26",
    alignItems: "center",
    justifyContent: "center",
  },
  placeholderFrame: {
    width: 28,
    height: 22,
    borderWidth: 2,
    borderColor: "#4a4a5a",
    borderRadius: 3,
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    opacity: 0.6,
  },
  placeholderLine: {
    width: 14,
    height: 2,
    backgroundColor: "#4a4a5a",
    borderRadius: 1,
  },
  placeholderLineShort: { width: 8 },
});
