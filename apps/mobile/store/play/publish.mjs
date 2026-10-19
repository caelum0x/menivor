// Uploads Comet Lanes to Google Play through the Android Publisher API v3
// (edits flow): AAB -> track release -> listing text -> images -> commit.
// Zero dependencies: the service-account JWT is signed with node:crypto.
//
// Usage (owner or agent, after the Play app record exists):
//   GOOGLE_PLAY_SA_JSON=/path/to/service-account.json \
//   node store/play/publish.mjs --aab <path.aab> [--track alpha] [--status draft] [--dry-run]
// or read the key from the macOS Keychain:
//   GOOGLE_PLAY_SA_KEYCHAIN_SERVICE=<service name> node store/play/publish.mjs ...
//
// Defaults: track "alpha" (Play's closed testing track), status "draft". A brand
// new app only accepts draft releases until its first release is rolled out in
// the Console. See PUBLISHING.md.
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const here = path.dirname(new URL(import.meta.url).pathname);
const listing = JSON.parse(fs.readFileSync(path.join(here, "listing.json"), "utf8"));
const PKG = listing.packageName;
const API = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications";
const UPLOAD = "https://androidpublisher.googleapis.com/upload/androidpublisher/v3/applications";

const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : fallback;
};
const dryRun = args.includes("--dry-run");
const aabPath = opt("aab");
const track = opt("track", "alpha");
const status = opt("status", "draft");
if (!aabPath || !fs.existsSync(aabPath)) throw new Error("Pass --aab <path to the signed release .aab>");

function serviceAccount() {
  if (process.env.GOOGLE_PLAY_SA_JSON) return JSON.parse(fs.readFileSync(process.env.GOOGLE_PLAY_SA_JSON, "utf8"));
  const service = process.env.GOOGLE_PLAY_SA_KEYCHAIN_SERVICE;
  if (service) {
    const raw = execFileSync("security", ["find-generic-password", "-s", service, "-w"], { encoding: "utf8" });
    return JSON.parse(raw.trim());
  }
  throw new Error("Set GOOGLE_PLAY_SA_JSON or GOOGLE_PLAY_SA_KEYCHAIN_SERVICE");
}

async function accessToken(sa) {
  const now = Math.floor(Date.now() / 1000);
  const enc = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  const head = enc({ alg: "RS256", typ: "JWT" });
  const claim = enc({ iss: sa.client_email, scope: "https://www.googleapis.com/auth/androidpublisher", aud: sa.token_uri, iat: now, exp: now + 3000 });
  const sig = crypto.sign("RSA-SHA256", Buffer.from(`${head}.${claim}`), sa.private_key).toString("base64url");
  const res = await fetch(sa.token_uri, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer", assertion: `${head}.${claim}.${sig}` }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(`token: ${res.status} ${JSON.stringify(body)}`);
  return body.access_token;
}

const sa = serviceAccount();
const token = await accessToken(sa);
async function call(method, url, body, contentType = "application/json") {
  const res = await fetch(url, {
    method,
    headers: { Authorization: `Bearer ${token}`, "content-type": contentType },
    body: body === undefined ? undefined : contentType === "application/json" ? JSON.stringify(body) : body,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`${method} ${url} -> ${res.status} ${text}`);
  return text ? JSON.parse(text) : null;
}

const edit = await call("POST", `${API}/${PKG}/edits`, {});
const E = `${API}/${PKG}/edits/${edit.id}`;
const U = `${UPLOAD}/${PKG}/edits/${edit.id}`;
console.log("edit", edit.id);

const bundle = await call("POST", `${U}/bundles?uploadType=media`, fs.readFileSync(aabPath), "application/octet-stream");
console.log("uploaded bundle versionCode", bundle.versionCode);

await call("PUT", `${E}/tracks/${track}`, {
  track,
  releases: [{ name: `1.0.0 (${bundle.versionCode})`, versionCodes: [String(bundle.versionCode)], status, releaseNotes: [{ language: listing.language, text: "First release of Comet Lanes." }] }],
});
console.log(`track ${track}: release ${status}`);

await call("PUT", `${E}/listings/${listing.language}`, {
  language: listing.language,
  title: listing.title,
  shortDescription: listing.shortDescription,
  fullDescription: listing.fullDescription,
  video: listing.video,
});
await call("PATCH", `${E}/details`, {
  contactWebsite: listing.contactWebsite,
  defaultLanguage: listing.language,
  ...(listing.contactEmail.includes("@") ? { contactEmail: listing.contactEmail } : {}),
});
console.log("listing text and details set");

async function replaceImages(type, files) {
  await call("DELETE", `${E}/listings/${listing.language}/${type}`);
  for (const f of files) {
    await call("POST", `${U}/listings/${listing.language}/${type}?uploadType=media`, fs.readFileSync(path.join(here, f)), "image/png");
  }
  console.log(type, files.length);
}
await replaceImages("icon", [listing.images.icon]);
await replaceImages("featureGraphic", [listing.images.featureGraphic]);
await replaceImages("phoneScreenshots", listing.images.phoneScreenshots);

if (dryRun) {
  await call("POST", `${E}:validate`);
  await call("DELETE", E);
  console.log("validated and discarded (dry run)");
} else {
  await call("POST", `${E}:commit`);
  console.log("committed edit", edit.id);
}
