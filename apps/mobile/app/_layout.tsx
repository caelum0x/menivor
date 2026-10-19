import { useCallback, useEffect, useMemo, useState } from "react";

import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";

import {
  SessionContext,
  SupabaseAuthProvider,
  clearApiKey,
  getOrCreateInstallId,
  getSupabaseClient,
  loadApiKey,
  saveApiKey,
  type SessionValue,
} from "@/src/shared/auth";
import { unregisterPushToken } from "@/lib/api";
import { RevenueCatProvider } from "@/src/shared/billing";
import { PushProvider } from "@/src/shared/notifications";
import { ensureLocalFolderMigrated } from "@/src/shared/media/local-folder";
import { colors } from "@/src/shared/theme";
import { gateScreen } from "@/src/shared/release/RouteGate";

/** Upper bound on the sign-out push-token DELETE so sign-out stays instant. */
const PUSH_UNREGISTER_TIMEOUT_MS = 4000;

/**
 * Root layout. Loads the persisted API key on startup and provides the
 * session (key + sign in/out) to the whole navigation tree. Screens read it
 * via `useSession()` and pass `apiKey` as the `token` on API calls.
 */
export default function RootLayout() {
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // One-time move of device-local files from reelforge/ to menivor/; readers
    // also await it, so this only starts it early. Never throws.
    void ensureLocalFolderMigrated();
  }, []);

  useEffect(() => {
    let active = true;
    loadApiKey()
      .then((key) => {
        if (active) setApiKey(key);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const signIn = useCallback(async (key: string) => {
    const trimmed = key.trim();
    await saveApiKey(trimmed);
    setApiKey(trimmed);
  }, []);

  const signOut = useCallback(async () => {
    // Detach this install from the outgoing account's push delivery BEFORE the
    // key is dropped (the DELETE is authenticated with that key). Bounded so a
    // slow or offline network never blocks signing out; on failure the next
    // account's registration re-owns the install row server-side.
    const outgoingKey = await loadApiKey().catch(() => null);
    if (outgoingKey) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), PUSH_UNREGISTER_TIMEOUT_MS);
      try {
        const installId = await getOrCreateInstallId();
        await unregisterPushToken(installId, {
          token: outgoingKey,
          signal: controller.signal,
        });
      } catch (error) {
        console.warn("Push token unregister failed during sign-out", error);
      } finally {
        clearTimeout(timer);
      }
    }
    await clearApiKey();
    setApiKey(null);
    // Also drop the Apple/Google (Supabase) identity so the next person on this
    // device does not inherit the previous user's linked account. Local scope
    // only: other devices signed in with the same identity stay signed in.
    const supabase = getSupabaseClient();
    if (supabase) {
      await supabase.auth.signOut({ scope: "local" }).catch(() => undefined);
    }
  }, []);

  const value = useMemo<SessionValue>(
    () => ({ apiKey, loading, signIn, signOut }),
    [apiKey, loading, signIn, signOut],
  );

  return (
    <SessionContext.Provider value={value}>
      <RevenueCatProvider>
        <SupabaseAuthProvider>
        <PushProvider>
        <StatusBar style="light" />
        <Stack
          screenLayout={gateScreen}
          screenOptions={{
            headerStyle: { backgroundColor: colors.bg },
            headerTintColor: colors.textPrimary,
            headerTitleStyle: { color: colors.textPrimary },
            contentStyle: { backgroundColor: colors.bg },
          }}
        >
        <Stack.Screen name="index" options={{ headerShown: false }} />
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="waitlist" options={{ headerShown: false }} />
        <Stack.Screen name="beta-request" options={{ title: "Early access" }} />
        <Stack.Screen
          name="job/[id]"
          options={{ title: "Job", presentation: "card" }}
        />
        <Stack.Screen
          name="brand"
          options={{ title: "Brand Watermark", presentation: "card" }}
        />
        <Stack.Screen
          name="ideas"
          options={{ title: "Spark", presentation: "card" }}
        />
        <Stack.Screen
          name="performance"
          options={{ title: "Hook Performance", presentation: "card" }}
        />
        <Stack.Screen
          name="marketplace"
          options={{ title: "Template Marketplace", presentation: "card" }}
        />
        <Stack.Screen
          name="notifications"
          options={{ title: "Notifications", presentation: "card" }}
        />
        <Stack.Screen
          name="calendar"
          options={{ title: "Publishing Calendar", presentation: "card" }}
        />
        <Stack.Screen
          name="scheduled"
          options={{ title: "Scheduled", presentation: "card" }}
        />
        <Stack.Screen
          name="analytics"
          options={{ title: "Creator Dashboard", presentation: "card" }}
        />
        <Stack.Screen
          name="sso"
          options={{ title: "Enterprise SSO", presentation: "card" }}
        />
        <Stack.Screen
          name="capture/screen-import"
          options={{ title: "Import Footage", presentation: "card" }}
        />
        <Stack.Screen
          name="capture/index"
          options={{ title: "Capture", presentation: "card" }}
        />
        <Stack.Screen
          name="capture/trim"
          options={{ title: "Trim & Export", presentation: "card" }}
        />
        <Stack.Screen
          name="editor"
          options={{ title: "Timeline Editor", presentation: "card" }}
        />
        <Stack.Screen
          name="hook-lab"
          options={{ title: "Hook Score Lab", presentation: "card" }}
        />
        <Stack.Screen
          name="retention-lab"
          options={{ title: "Retention Lab", presentation: "card" }}
        />
        <Stack.Screen
          name="ab-lab"
          options={{ title: "A/B Winner Lab", presentation: "card" }}
        />
        <Stack.Screen
          name="trend-lab"
          options={{ title: "Trend Lab", presentation: "card" }}
        />
        <Stack.Screen
          name="diffusion-lab"
          options={{ title: "Diffusion Planner", presentation: "card" }}
        />
        <Stack.Screen
          name="effects-lab"
          options={{ title: "Effects Lab", presentation: "card" }}
        />
        <Stack.Screen
          name="model-governance"
          options={{ title: "Model Governance", presentation: "card" }}
        />
        <Stack.Screen
          name="media-gateway"
          options={{ title: "Media Gateway", presentation: "card" }}
        />
        <Stack.Screen
          name="privacy"
          options={{ title: "Privacy & Data", presentation: "card" }}
        />
        <Stack.Screen
          name="support"
          options={{ title: "Support", presentation: "card" }}
        />
        <Stack.Screen
          name="account-access"
          options={{ title: "Account Access", presentation: "card" }}
        />
        <Stack.Screen
          name="leaderboard"
          options={{ title: "Creator Leaderboard", presentation: "card" }}
        />
        <Stack.Screen
          name="creator/[id]"
          options={{ title: "Creator", presentation: "card" }}
        />
        <Stack.Screen
          name="experiments"
          options={{ title: "Experiments", presentation: "card" }}
        />
        <Stack.Screen
          name="speak-studio"
          options={{ title: "Speak Studio", presentation: "card" }}
        />
        <Stack.Screen
          name="social-sign-in"
          options={{ title: "Sign in", presentation: "card" }}
        />
        <Stack.Screen
          name="library"
          options={{ title: "Library & Studio", presentation: "card" }}
        />
        {/* Catalog cluster */}
        <Stack.Screen name="catalog/index" options={{ title: "Catalog", presentation: "card" }} />
        <Stack.Screen
          name="catalog/caption-styles"
          options={{ title: "Caption Styles", presentation: "card" }}
        />
        <Stack.Screen name="catalog/music" options={{ title: "Music Library", presentation: "card" }} />
        <Stack.Screen name="catalog/layouts" options={{ title: "Layouts", presentation: "card" }} />
        <Stack.Screen name="catalog/templates" options={{ title: "Templates", presentation: "card" }} />
        <Stack.Screen name="catalog/hooks" options={{ title: "Hook Lines", presentation: "card" }} />
        <Stack.Screen
          name="catalog/cover-styles"
          options={{ title: "Cover Styles", presentation: "card" }}
        />
        <Stack.Screen
          name="catalog/dub-languages"
          options={{ title: "Dub Languages", presentation: "card" }}
        />
        {/* Studio cluster */}
        <Stack.Screen name="studio/avatars" options={{ title: "Avatar Gallery", presentation: "card" }} />
        <Stack.Screen name="studio/avatar/[id]" options={{ title: "Avatar", presentation: "card" }} />
        <Stack.Screen name="studio/voices" options={{ title: "Voice Library", presentation: "card" }} />
        <Stack.Screen name="uploads" options={{ title: "Uploads", presentation: "card" }} />
        <Stack.Screen name="film" options={{ title: "Film Studio", presentation: "card" }} />
        <Stack.Screen name="invite/[token]" options={{ title: "Team invite", presentation: "card" }} />
        {/* Wallet cluster */}
        <Stack.Screen name="wallet/index" options={{ title: "Wallet", presentation: "card" }} />
        <Stack.Screen name="wallet/history" options={{ title: "Transactions", presentation: "card" }} />
        <Stack.Screen name="wallet/top-up" options={{ title: "Add credit", presentation: "card" }} />
        <Stack.Screen name="wallet/transfer" options={{ title: "Send tokens", presentation: "card" }} />
        <Stack.Screen name="wallet/plans" options={{ title: "Plans & Usage", presentation: "card" }} />
        <Stack.Screen
          name="wallet/destinations"
          options={{ title: "Receive Identities", presentation: "card" }}
        />
        <Stack.Screen
          name="wallet/billing-history"
          options={{ title: "Billing history", presentation: "card" }}
        />
        {/* Insights cluster */}
        <Stack.Screen name="insights/index" options={{ title: "Insights", presentation: "card" }} />
        <Stack.Screen
          name="insights/referral"
          options={{ title: "Referral Program", presentation: "card" }}
        />
        <Stack.Screen name="insights/presets" options={{ title: "Reel Presets", presentation: "card" }} />
        {/* Connections cluster */}
        <Stack.Screen
          name="connections/manage"
          options={{ title: "Connected Accounts", presentation: "card" }}
        />
        <Stack.Screen
          name="connections/publish"
          options={{ title: "Publish a Reel", presentation: "card" }}
        />
        <Stack.Screen
          name="connections/social-copy"
          options={{ title: "AI Social Copy", presentation: "card" }}
        />
        {/* Account cluster */}
        <Stack.Screen
          name="account/workspaces/index"
          options={{ title: "Team & Workspaces", presentation: "card" }}
        />
        <Stack.Screen
          name="account/workspaces/members"
          options={{ title: "Members & Invites", presentation: "card" }}
        />
        <Stack.Screen
          name="account/workspaces/roles"
          options={{ title: "Team Roles", presentation: "card" }}
        />
        <Stack.Screen
          name="account/webhooks"
          options={{ title: "Webhooks", presentation: "card" }}
        />
        <Stack.Screen
          name="account/settings"
          options={{ title: "Account & Settings", presentation: "card" }}
        />
        <Stack.Screen
          name="account/developer-keys"
          options={{ title: "Developer & API Keys", presentation: "card" }}
        />
        <Stack.Screen
          name="account/provider-keys"
          options={{ title: "Provider Keys", presentation: "card" }}
        />
        {/* Catalog cluster — round 1 additions */}
        <Stack.Screen
          name="catalog/model-catalog"
          options={{ title: "Model Catalog", presentation: "card" }}
        />
        <Stack.Screen
          name="catalog/model/[id]"
          options={{ title: "Model", presentation: "card" }}
        />
        <Stack.Screen
          name="catalog/provider-health"
          options={{ title: "Provider Health", presentation: "card" }}
        />
        <Stack.Screen
          name="catalog/quote"
          options={{ title: "Estimate Cost", presentation: "card" }}
        />
        <Stack.Screen
          name="catalog/presets"
          options={{ title: "Motion & VFX", presentation: "card" }}
        />
        {/* Studio · Caption Studio cluster */}
        <Stack.Screen
          name="studio/captions/index"
          options={{ title: "Caption Studio", presentation: "card" }}
        />
        <Stack.Screen
          name="studio/captions/hook-score"
          options={{ title: "Hook Score", presentation: "card" }}
        />
        <Stack.Screen
          name="studio/captions/hormozi"
          options={{ title: "Punch Captions", presentation: "card" }}
        />
        <Stack.Screen
          name="studio/captions/safezones"
          options={{ title: "Safe Zones", presentation: "card" }}
        />
        <Stack.Screen
          name="studio/captions/loop-check"
          options={{ title: "Loop Check", presentation: "card" }}
        />
        <Stack.Screen
          name="studio/captions/beat-fit"
          options={{ title: "Beat Fit", presentation: "card" }}
        />
        <Stack.Screen
          name="studio/captions/seo"
          options={{ title: "Caption SEO", presentation: "card" }}
        />
        {/* Studio · Character Canon cluster */}
        <Stack.Screen
          name="studio/characters/canon/index"
          options={{ title: "Character Canon", presentation: "card" }}
        />
        <Stack.Screen
          name="studio/characters/canon/[id]/index"
          options={{ title: "Canon", presentation: "card" }}
        />
        <Stack.Screen
          name="studio/characters/canon/[id]/versions/[version]"
          options={{ title: "Canon Version", presentation: "card" }}
        />
        {/* Studio · Motion Presets cluster */}
        <Stack.Screen
          name="studio/motion/index"
          options={{ title: "Motion Presets", presentation: "card" }}
        />
        <Stack.Screen
          name="studio/motion/history"
          options={{ title: "Compile History", presentation: "card" }}
        />
        <Stack.Screen
          name="studio/motion/[id]"
          options={{ title: "Motion Preset", presentation: "card" }}
        />
        {/* Repurpose · Content Engine cluster */}
        <Stack.Screen
          name="repurpose/clipping/index"
          options={{ title: "Content Engine", presentation: "card" }}
        />
        <Stack.Screen
          name="repurpose/clipping/[id]"
          options={{ title: "Repurpose Job", presentation: "card" }}
        />
        <Stack.Screen
          name="repurpose/clipping/clip/[id]"
          options={{ title: "Auto-Clip Job", presentation: "card" }}
        />
        <Stack.Screen
          name="repurpose/clipping/ingest"
          options={{ title: "Import from URL", presentation: "card" }}
        />
        {/* Account · Admin Console cluster (round 2) */}
        <Stack.Screen
          name="account/admin/index"
          options={{ title: "Admin Console", presentation: "card" }}
        />
        <Stack.Screen
          name="account/admin/users"
          options={{ title: "Users", presentation: "card" }}
        />
        <Stack.Screen
          name="account/admin/workspaces"
          options={{ title: "Workspaces", presentation: "card" }}
        />
        <Stack.Screen
          name="account/admin/revenue"
          options={{ title: "Revenue", presentation: "card" }}
        />
        <Stack.Screen
          name="account/admin/jobs"
          options={{ title: "All Jobs", presentation: "card" }}
        />
        <Stack.Screen
          name="account/admin/retention"
          options={{ title: "Retention", presentation: "card" }}
        />
        <Stack.Screen
          name="account/admin/erasure-requests"
          options={{ title: "Erasure Requests", presentation: "card" }}
        />
        {/* Insights · Winning Templates (round 2) */}
        <Stack.Screen
          name="insights/winning-templates"
          options={{ title: "Winning Templates", presentation: "card" }}
        />
        {/* Studio · Template Studio cluster (round 2) */}
        <Stack.Screen
          name="studio/templates"
          options={{ title: "Template Studio", presentation: "card" }}
        />
        <Stack.Screen
          name="studio/template/[slug]"
          options={{ title: "Template Preview", presentation: "card" }}
        />
        {/* Workspaces · Data Retention (round 2) */}
        <Stack.Screen
          name="workspaces/retention"
          options={{ title: "Data Retention", presentation: "card" }}
        />
        {/* Round 3 additions */}
        <Stack.Screen
          name="catalog/reddit-story"
          options={{ title: "Reddit Story", presentation: "card" }}
        />
        <Stack.Screen
          name="connections/social-metadata"
          options={{ title: "Draft Social Copy", presentation: "card" }}
        />
        <Stack.Screen
          name="wallet/transfer-policy"
          options={{ title: "Send limits", presentation: "card" }}
        />
        {/* Round 4 additions */}
        {/* Account · Personal API Keys cluster */}
        <Stack.Screen
          name="account/api-keys/[id]"
          options={{ title: "API Key", presentation: "card" }}
        />
        {/* Account · Brand Voices cluster */}
        <Stack.Screen
          name="account/voices/index"
          options={{ title: "Brand Voices", presentation: "card" }}
        />
        <Stack.Screen
          name="account/voices/[id]"
          options={{ title: "Voice", presentation: "card" }}
        />
        {/* Account · Custom Avatars cluster */}
        <Stack.Screen
          name="account/avatars/index"
          options={{ title: "Custom Avatars", presentation: "card" }}
        />
        <Stack.Screen
          name="account/avatars/[id]"
          options={{ title: "Avatar", presentation: "card" }}
        />
        {/* Studio · Script Studio cluster */}
        <Stack.Screen
          name="studio/scripts/index"
          options={{ title: "Script Studio", presentation: "card" }}
        />
        <Stack.Screen
          name="studio/scripts/generate"
          options={{ title: "Generate Script", presentation: "card" }}
        />
        <Stack.Screen
          name="studio/scripts/[id]"
          options={{ title: "Edit Script", presentation: "card" }}
        />
        {/* Jobs · Task Queue cluster */}
        <Stack.Screen
          name="jobs/reels/tasks/index"
          options={{ title: "Tasks", presentation: "card" }}
        />
        <Stack.Screen
          name="jobs/reels/tasks/[id]"
          options={{ title: "Task", presentation: "card" }}
        />
        <Stack.Screen
          name="jobs/reels/batch/[batchId]"
          options={{ title: "Batch", presentation: "card" }}
        />
        {/* Reels · Render Job detail */}
        <Stack.Screen
          name="reels/render-job"
          options={{ title: "Render Job", presentation: "card" }}
        />
        {/* Catalog · Pull Trends */}
        <Stack.Screen
          name="catalog/trend-pull"
          options={{ title: "Pull Trends", presentation: "card" }}
        />
        {/* Round 5 additions */}
        {/* Catalog · Backgrounds gallery */}
        <Stack.Screen
          name="catalog/backgrounds"
          options={{ title: "Backgrounds", presentation: "card" }}
        />
        {/* Catalog · Stock Libraries cluster */}
        <Stack.Screen
          name="catalog/studio/index"
          options={{ title: "Stock Libraries", presentation: "card" }}
        />
        <Stack.Screen
          name="catalog/studio/stock-music"
          options={{ title: "Music Library", presentation: "card" }}
        />
        <Stack.Screen
          name="catalog/studio/stock-materials"
          options={{ title: "Video Materials", presentation: "card" }}
        />
        {/* Navigation Hub (discoverability) cluster */}
        <Stack.Screen
          name="navigation/discoverability/index"
          options={{ title: "Navigation Hub", presentation: "card" }}
        />
        <Stack.Screen
          name="navigation/discoverability/[group]"
          options={{ title: "Browse", presentation: "card" }}
        />
        </Stack>
        </PushProvider>
        </SupabaseAuthProvider>
      </RevenueCatProvider>
    </SessionContext.Provider>
  );
}
