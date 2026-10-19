import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Store-readiness guard for the iOS submission (ASC "Menivor: AI Video Maker",
 * id 6809286411). Pins the values App Store Connect / App Review check so a
 * config edit cannot silently ship a mismatched bundle id, a missing privacy
 * manifest, a dev API base, or a provider AI key inside the binary.
 */

const APP_ROOT = path.resolve(__dirname, "../../../..");

type Json = Record<string, any>;
const readJson = (file: string): Json =>
  JSON.parse(readFileSync(path.join(APP_ROOT, file), "utf8")) as Json;

const appJson = readJson("app.json").expo as Json;
const easJson = readJson("eas.json");

const SOURCE_DIRS = ["app", "src", "lib", "components"];

function sourceFiles(dir: string): string[] {
  const abs = path.join(APP_ROOT, dir);
  const out: string[] = [];
  for (const name of readdirSync(abs)) {
    if (name === "__tests__" || name === "node_modules") continue;
    const full = path.join(abs, name);
    if (statSync(full).isDirectory()) {
      out.push(...sourceFiles(path.join(dir, name)));
    } else if (/\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name)) {
      out.push(full);
    }
  }
  return out;
}

const allSources = SOURCE_DIRS.flatMap(sourceFiles).map((file) => ({
  file,
  text: readFileSync(file, "utf8"),
}));

describe("iOS app config", () => {
  it("ships under the bundle id registered in App Store Connect", () => {
    expect(appJson.ios.bundleIdentifier).toBe("com.arhansuba.menivor");
    expect(easJson.submit.production.ios.ascAppId).toBe("6809286411");
  });

  it("declares a privacy manifest with the required-reason APIs and no tracking", () => {
    const manifest = appJson.ios.privacyManifests;
    expect(manifest.NSPrivacyTracking).toBe(false);
    const reasons = Object.fromEntries(
      (manifest.NSPrivacyAccessedAPITypes as Json[]).map((entry) => [
        entry.NSPrivacyAccessedAPIType,
        entry.NSPrivacyAccessedAPITypeReasons,
      ]),
    );
    expect(reasons.NSPrivacyAccessedAPICategoryUserDefaults).toContain("CA92.1");
    expect(reasons.NSPrivacyAccessedAPICategoryFileTimestamp).toContain("C617.1");
    expect(reasons.NSPrivacyAccessedAPICategorySystemBootTime).toContain("35F9.1");
    expect(reasons.NSPrivacyAccessedAPICategoryDiskSpace).toContain("E174.1");
  });

  it("explains every permission the app requests", () => {
    const plist = appJson.ios.infoPlist as Json;
    for (const key of [
      "NSPhotoLibraryUsageDescription",
      "NSMicrophoneUsageDescription",
      "NSCameraUsageDescription",
    ]) {
      expect(typeof plist[key]).toBe("string");
      expect((plist[key] as string).length).toBeGreaterThan(20);
    }
  });

  it("answers the export-compliance question up front", () => {
    expect(appJson.ios.config?.usesNonExemptEncryption).toBe(false);
  });
});

describe("production build env", () => {
  const env = easJson.build.production.env as Record<string, string>;

  it("points at the production API with the waitlist off", () => {
    expect(env.EXPO_PUBLIC_API_BASE).toBe("https://api.menivor.com/api/v1");
    expect(env.EXPO_PUBLIC_WAITLIST_MODE).toBe("0");
  });

  it("never bakes a dev host into a store build", () => {
    for (const profile of ["production", "preview"]) {
      const values = Object.values(easJson.build[profile].env ?? {}).join("\n");
      expect(values).not.toMatch(/localhost|127\.0\.0\.1|ngrok|192\.168\./);
    }
  });

  it("carries no AI-provider key", () => {
    for (const profile of Object.keys(easJson.build)) {
      for (const [key, value] of Object.entries(easJson.build[profile].env ?? {})) {
        expect(key).not.toMatch(/ANTHROPIC|OPENAI|GROQ|OPENROUTER|REPLICATE|ELEVENLABS|FAL_/);
        expect(String(value)).not.toMatch(/sk-ant|gsk_|sk-or-|r8_[A-Za-z0-9]{10}/);
      }
    }
  });
});

describe("mobile source", () => {
  it("reads no AI-provider key and embeds no provider secret", () => {
    const offenders = allSources.filter(({ text }) =>
      /EXPO_PUBLIC_(ANTHROPIC|OPENAI|GROQ|OPENROUTER|REPLICATE|ELEVENLABS|FAL)[A-Z_]*KEY|sk-ant-|gsk_[A-Za-z0-9]{10}|sk-or-v1/.test(
        text,
      ),
    );
    expect(offenders.map((o) => path.relative(APP_ROOT, o.file))).toEqual([]);
  });

  it("references no retired model id", () => {
    const offenders = allSources.filter(({ text }) =>
      /llama-3\.3-70b-versatile|llama-4-scout-17b-16e-instruct/.test(text),
    );
    expect(offenders.map((o) => path.relative(APP_ROOT, o.file))).toEqual([]);
  });

  it("renders no emoji glyphs in UI strings", () => {
    const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u;
    const offenders: string[] = [];
    for (const { file, text } of allSources) {
      text.split("\n").forEach((line, i) => {
        const trimmed = line.trim();
        if (trimmed.startsWith("*") || trimmed.startsWith("//") || trimmed.startsWith("/*")) return;
        if (emoji.test(line)) offenders.push(`${path.relative(APP_ROOT, file)}:${i + 1}`);
      });
    }
    expect(offenders).toEqual([]);
  });
});
