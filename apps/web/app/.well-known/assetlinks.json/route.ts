/**
 * Digital Asset Links file for the Menivor Android app (package
 * `com.menivor.app`). The app declares an `https://menivor.com/r/*` and
 * `/invite/*` autoVerify intent filter (see apps/mobile/app.json); without
 * this file Android opens those links in the browser instead of the app.
 * Served as JSON at the well-known path Android's Digital Asset Links
 * service fetches (https://menivor.com/.well-known/assetlinks.json).
 *
 * The fingerprint below is the per-app Play *upload* key's SHA-256
 * certificate fingerprint (`~/.config/products-keys/menivor/upload.jks`,
 * alias `menivor-upload`), which is what signs local/EAS release builds
 * before they reach Play. It is public by design (a certificate hash, not a
 * secret) and is exactly what Android checks before Play App Signing takes
 * over a release.
 *
 * Once the Android app exists in Play Console and Play App Signing is
 * enabled (default for new apps), Play re-signs the distributed APK with its
 * own app-signing key, which gets a DIFFERENT SHA-256 fingerprint. That
 * fingerprint only appears on the Play Console "App integrity" page
 * (Setup > App integrity > App signing key certificate), which requires an
 * owner login to Play Console — add it to the `fingerprints` array below
 * alongside the upload key's once the owner pulls it, so links verify for
 * production-downloaded installs too.
 */
export const dynamic = "force-static";

const PACKAGE_NAME = "com.menivor.app";

// Upload-key fingerprint (safe to publish; not the Play app-signing key).
const UPLOAD_KEY_SHA256_FINGERPRINT =
  "4A:08:88:0C:FC:2A:4D:16:D4:39:4E:1B:6C:85:B1:A4:26:D4:A2:5A:CE:80:EC:00:19:E1:0F:4D:F5:CB:8E:8F";

export function GET(): Response {
  const body = [
    {
      relation: ["delegate_permission/common.handle_all_urls"],
      target: {
        namespace: "android_app",
        package_name: PACKAGE_NAME,
        sha256_cert_fingerprints: [UPLOAD_KEY_SHA256_FINGERPRINT],
      },
    },
  ];
  return new Response(JSON.stringify(body), {
    headers: {
      "content-type": "application/json",
      "cache-control": "public, max-age=3600",
    },
  });
}
