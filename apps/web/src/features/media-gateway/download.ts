import type { Modality } from "./api";

const EXT: Record<Modality, string> = { image: "png", video: "mp4", audio: "mp3" };

/** A stable, human-readable filename for a saved generation. */
export function generationFilename(modality: Modality, model: string): string {
  const slug = model.replace(/[^a-z0-9]+/gi, "-").replace(/^-+|-+$/g, "").toLowerCase() || "generation";
  return `menivor-${slug}.${EXT[modality]}`;
}

/**
 * Save a generated asset to the user's device. Presigned R2 URLs are CORS-open
 * for GET, so we fetch the bytes into a blob and trigger a real download with the
 * chosen filename; if the fetch is blocked (CORS/expired), we fall back to opening
 * the asset in a new tab so the user can still save it manually. Returns `true`
 * when a blob download was triggered.
 */
export async function downloadUrl(url: string, filename: string): Promise<boolean> {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Revoke on the next tick so the click has consumed the URL.
    setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
    return true;
  } catch {
    window.open(url, "_blank", "noopener,noreferrer");
    return false;
  }
}

/** Export an already-verified JSON object without another network request. */
export function downloadJson(value: unknown, filename: string): void {
  const blob = new Blob([`${JSON.stringify(value, null, 2)}\n`], {
    type: "application/json",
  });
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}
