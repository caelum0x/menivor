import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import {
  ApiError,
  generateSocial,
  isAbortError,
  listSocialPlatforms,
} from "@/lib/api";
import type { SocialMeta, SocialPlatform } from "@/lib/types";

import { CopyableField } from "./CopyableField";
import { PlatformSelector } from "./PlatformSelector";
import { FALLBACK_SOCIAL_PLATFORMS } from "./platforms";

export interface SocialSectionProps {
  /** The finished job to generate post copy for. */
  jobId: string;
  /** Signed-in user's API key (x-api-key), or undefined for the app key. */
  token?: string;
}

type GenState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; meta: SocialMeta };

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

/**
 * "Caption & Hashtags" section for the job screen. The creator picks a target
 * platform (TikTok / Instagram / YouTube Shorts) and taps Generate to get an
 * optimized post title, caption and hashtags tailored to it
 * (POST /jobs/{id}/social — built on MPT's vendored
 * `llm.generate_social_metadata`). Each field has a Copy button so the creator
 * can paste it when posting. Nothing is generated until the creator opts in.
 */
export function SocialSection({ jobId, token }: Readonly<SocialSectionProps>) {
  const [platforms, setPlatforms] = useState<readonly SocialPlatform[]>(
    FALLBACK_SOCIAL_PLATFORMS,
  );
  const [selectedId, setSelectedId] = useState<string>(
    FALLBACK_SOCIAL_PLATFORMS[0]?.id ?? "",
  );
  const [state, setState] = useState<GenState>({ status: "idle" });

  // Load the platform catalog; fall back to the bundled list on any failure so
  // the selector always has options.
  useEffect(() => {
    const controller = new AbortController();
    listSocialPlatforms({ token, signal: controller.signal })
      .then((list) => {
        if (list.length === 0) return;
        setPlatforms(list);
        setSelectedId((prev) =>
          list.some((p) => p.id === prev) ? prev : list[0].id,
        );
      })
      .catch((err) => {
        // Keep the fallback catalog; ignore aborts and degrade silently.
        if (isAbortError(err)) return;
      });
    return () => controller.abort();
  }, [token]);

  const generate = useCallback(async () => {
    if (!selectedId) return;
    setState({ status: "loading" });
    try {
      const meta = await generateSocial(jobId, { platform: selectedId }, { token });
      setState({ status: "ready", meta });
    } catch (err) {
      if (isAbortError(err)) return;
      setState({
        status: "error",
        message: describe(err, "Couldn't generate caption & hashtags. Try again."),
      });
    }
  }, [jobId, selectedId, token]);

  const busy = state.status === "loading";
  const hashtagsText = useMemo(() => {
    if (state.status !== "ready") return "";
    return state.meta.hashtags.join(" ");
  }, [state]);

  return (
    <View style={styles.container}>
      <Text style={styles.subtitle}>
        Generate an optimized post title, caption and hashtags tailored to a
        platform, then copy them when you post. Optional.
      </Text>

      <PlatformSelector
        platforms={platforms}
        selectedId={selectedId}
        onSelect={setSelectedId}
        disabled={busy}
      />

      <Pressable
        style={[styles.generate, busy && styles.disabled]}
        onPress={() => void generate()}
        disabled={busy || !selectedId}
        accessibilityRole="button"
        accessibilityLabel="Generate caption and hashtags for this reel"
        accessibilityState={{ disabled: busy || !selectedId }}
      >
        {busy ? (
          <ActivityIndicator color="#E6C76A" />
        ) : (
          <Text style={styles.generateText}>
            {state.status === "ready" ? "Regenerate" : "Generate"}
          </Text>
        )}
      </Pressable>

      {state.status === "error" ? (
        <Text style={styles.error}>{state.message}</Text>
      ) : null}

      {state.status === "ready" ? (
        <View style={styles.results}>
          <CopyableField label="Title" value={state.meta.title} />
          <CopyableField label="Caption" value={state.meta.caption} />
          <CopyableField
            label="Hashtags"
            value={hashtagsText}
            display={hashtagsText}
            emptyText="No hashtags"
          />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 10, marginTop: 8 },
  subtitle: { color: "#8b8b9b", fontSize: 13, lineHeight: 18 },
  generate: {
    backgroundColor: "#0f0f10",
    borderColor: "#E6C76A",
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  generateText: { color: "#E6C76A", fontSize: 15, fontWeight: "700" },
  disabled: { opacity: 0.5 },
  error: { color: "#E0847F", fontSize: 14 },
  results: { gap: 10, marginTop: 2 },
});
