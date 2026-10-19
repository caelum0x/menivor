import type { PilotCapabilities } from "./generated/reelforge-v1.js";
export type GenerationFeature = "reels" | "broll";
export declare function canGenerate(capabilities: PilotCapabilities, feature: GenerationFeature): boolean;
export declare function canonicalGenerationRoute(capabilities: PilotCapabilities, feature: GenerationFeature): string;
