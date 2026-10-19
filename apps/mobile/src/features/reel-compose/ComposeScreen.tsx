import { useState } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";

import { useSession } from "@/src/shared/auth";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useGenerationCapabilities } from "@/src/shared/hooks";
import type { Job } from "@/lib/types";

import { TemplateBrowser } from "./components/TemplateBrowser";
import { TemplateInputForm } from "./components/TemplateInputForm";
import { GenerationReview } from "./components/GenerationReview";

type Stage =
  | { name: "browse" }
  | { name: "input"; slug: string }
  | { name: "review"; job: Job };

/**
 * Reel Compose — the template-first authoring flow: browse a proven format,
 * fill its inputs + attach footage, generate a real job, then review and
 * approve (keep) or redo. Every read/write carries the session token and the
 * job create is gated by the server-owned generation capability.
 */
export function ComposeScreen() {
  const router = useRouter();
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const capabilityState = useGenerationCapabilities(token);
  const generationAllowed =
    capabilityState.capabilities?.generation.reels === true;
  const params = useLocalSearchParams<{
    trend_id?: string | string[];
    subject?: string | string[];
    forecast_id?: string | string[];
  }>();
  const trendId = Array.isArray(params.trend_id) ? params.trend_id[0] : params.trend_id;
  const trendLabel = Array.isArray(params.subject) ? params.subject[0] : params.subject;
  const forecastId = Array.isArray(params.forecast_id) ? params.forecast_id[0] : params.forecast_id;
  const source = trendId
    ? { kind: "trend" as const, id: trendId, label: trendLabel || trendId, forecastId }
    : undefined;

  const [stage, setStage] = useState<Stage>({ name: "browse" });

  if (capabilityState.loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color="#E6C76A" />
        <Text style={styles.meta}>Checking generation availability…</Text>
      </View>
    );
  }

  switch (stage.name) {
    case "input":
      return (
        <TemplateInputForm
          token={token}
          slug={stage.slug}
          generationAllowed={generationAllowed}
          capabilityError={capabilityState.error}
          source={source}
          onGenerated={(job) => setStage({ name: "review", job })}
          onBack={() => setStage({ name: "browse" })}
        />
      );
    case "review":
      return (
        <GenerationReview
          token={token}
          initialJob={stage.job}
          onApprove={(job) =>
            router.replace(`/job/${encodeURIComponent(job.job_id)}`)
          }
          onStartOver={() => setStage({ name: "browse" })}
        />
      );
    case "browse":
    default:
      return (
        <TemplateBrowser
          token={token}
          onSelect={(slug) => setStage({ name: "input", slug })}
        />
      );
  }
}

const styles = StyleSheet.create({
  centered: {
    flex: 1,
    backgroundColor: "#0a0a0b",
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    gap: 12,
  },
  meta: { color: "#6f6c65", fontSize: 14, textAlign: "center" },
});
