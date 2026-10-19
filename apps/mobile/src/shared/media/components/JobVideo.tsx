import { useState } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";

import { ResizeMode, Video, type AVPlaybackStatus } from "expo-av";

/**
 * Shared 9:16 portrait video player (expo-av) for a final result or short
 * preview clip. Shows a loading spinner until the first frame is buffered and a
 * friendly error message if the source can't be played. Uses the poster frame
 * (when supplied) so the first paint is the thumbnail rather than a black box.
 */

export interface JobVideoProps {
  /** Absolute video URL (result_url or preview_key → URL). */
  uri: string;
  /** Optional poster image shown before playback starts. */
  posterUri?: string;
  /** Loop playback (used for the short teaser preview). */
  isLooping?: boolean;
  /** Start muted (used for the auto-teaser preview). */
  isMuted?: boolean;
  /** Reports real media duration once expo-av has loaded the source. */
  onDurationChange?: (durationSeconds: number) => void;
}

export function JobVideo({
  uri,
  posterUri,
  isLooping = false,
  isMuted = false,
  onDurationChange,
}: Readonly<JobVideoProps>) {
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);

  const onStatus = (status: AVPlaybackStatus) => {
    if (!status.isLoaded) {
      if (status.error) setErrored(true);
      return;
    }
    if (loading) setLoading(false);
    if (typeof status.durationMillis === "number" && status.durationMillis > 0) {
      onDurationChange?.(status.durationMillis / 1_000);
    }
  };

  if (errored) {
    return (
      <View style={[styles.frame, styles.center]}>
        <Text style={styles.errorText}>Couldn&apos;t play this video.</Text>
      </View>
    );
  }

  return (
    <View style={styles.frame}>
      <Video
        style={styles.video}
        source={{ uri }}
        useNativeControls
        resizeMode={ResizeMode.CONTAIN}
        isLooping={isLooping}
        isMuted={isMuted}
        usePoster={Boolean(posterUri)}
        posterSource={posterUri ? { uri: posterUri } : undefined}
        onLoadStart={() => setLoading(true)}
        onLoad={() => setLoading(false)}
        onError={() => setErrored(true)}
        onPlaybackStatusUpdate={onStatus}
      />
      {loading ? (
        <View style={styles.overlay} pointerEvents="none">
          <ActivityIndicator color="#E6C76A" size="large" />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  frame: {
    width: "100%",
    aspectRatio: 9 / 16,
    backgroundColor: "#000000",
    borderRadius: 12,
    overflow: "hidden",
  },
  video: { width: "100%", height: "100%" },
  center: { alignItems: "center", justifyContent: "center" },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
  },
  errorText: { color: "#ff9a9a", fontSize: 14, textAlign: "center", padding: 20 },
});
