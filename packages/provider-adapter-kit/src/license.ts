/** License-class registry + paid exclusion rule (mirror of `license.py`). */

export const LICENSE_CLASSES = ["commercial-safe", "non-commercial", "territorial"] as const;
export type LicenseClass = (typeof LICENSE_CLASSES)[number];

export const LICENSE_REGISTRY: Record<string, LicenseClass> = {
  "wan/wan-2.2": "commercial-safe",
  "lightricks/ltx-video": "commercial-safe",
  "black-forest-labs/flux-schnell": "commercial-safe",
  "genmo/mochi-1": "commercial-safe",
  "kwaivgi/kling-v1.6": "commercial-safe",
  "black-forest-labs/flux-dev": "non-commercial",
  "coqui/xtts-v2": "non-commercial",
  "SWivid/f5-tts": "non-commercial",
  "stabilityai/stable-video-diffusion": "non-commercial",
  "tencent/hunyuan-video": "territorial",
  "THUDM/cogvideox-5b": "territorial",
};

/** License class for a model (defaults to `territorial` = gate-before-use). */
export function licenseClass(modelId: string): LicenseClass {
  return LICENSE_REGISTRY[modelId] ?? "territorial";
}

export function canUseForPaid(modelId: string): boolean {
  return licenseClass(modelId) === "commercial-safe";
}
