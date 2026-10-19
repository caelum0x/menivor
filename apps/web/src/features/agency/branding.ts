/** Agency white-label branding — the watermark applied to client output (over /me/brand). */
import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type WatermarkPosition = "top_left" | "top_right" | "bottom_left" | "bottom_right" | "center";

export interface Brand {
  logo_key: string;
  position: WatermarkPosition;
  opacity: number; // 0..1
  enabled: boolean;
  logo_url?: string;
}

export function getBrand(options?: RequestOptions): Promise<Brand> {
  return apiRequest<Brand>("/me/brand", { options });
}

export function updateBrand(body: Partial<Brand>, options?: RequestOptions): Promise<Brand> {
  return apiRequest<Brand>("/me/brand", { method: "PUT", body, options });
}
