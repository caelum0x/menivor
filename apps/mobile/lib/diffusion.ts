import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface DiffusionForecast {
  forecast_id: string;
  content_type: DiffusionContentType;
  trend: {
    observation_id: string;
    trend_id: string;
    kind: string;
    label: string;
    observed_at: string | null;
  };
  model: string;
  steps: number;
  total_audience: number;
  expected_reach: number;
  adoption_fraction: number;
  assumption_notice: string;
  timeline: Array<{
    step: number;
    expected_reach: number;
    segments: Array<{
      node_id: string;
      label: string;
      activation_probability: number;
      expected_reach: number;
    }>;
  }>;
}

export type DiffusionContentType = "short_video" | "tutorial" | "product_demo" | "commentary";

export function forecastDiffusion(
  input: {
    trendObservationId: string;
    contentType: DiffusionContentType;
    directAudience: number;
    peerAudience: number;
    nicheAudience: number;
    hookStrength: number;
    shareRate: number;
  },
  options?: RequestOptions,
): Promise<DiffusionForecast> {
  const hookProbability = Math.max(0, Math.min(1, input.hookStrength / 100));
  const shareProbability = Math.max(0, Math.min(1, input.shareRate / 100));
  return apiRequest<DiffusionForecast>("/trends/diffusion-forecast", {
    method: "POST",
    body: {
      trend_observation_id: input.trendObservationId,
      content_type: input.contentType,
      nodes: [
        { node_id: "published", audience_size: 0, label: "Published post" },
        { node_id: "direct", audience_size: input.directAudience, label: "Direct audience" },
        { node_id: "peers", audience_size: input.peerAudience, label: "Peer audiences" },
        { node_id: "niche", audience_size: input.nicheAudience, label: "Niche discovery pool" },
      ],
      edges: [
        { source: "published", target: "direct", probability: hookProbability },
        { source: "direct", target: "peers", probability: shareProbability },
        { source: "peers", target: "niche", probability: shareProbability * 0.7 },
        { source: "direct", target: "niche", probability: shareProbability * 0.25 },
      ],
      seeds: ["published"],
      steps: 5,
    },
    options,
  });
}
