import { useEffect, useState } from "react";

import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { useRouter } from "expo-router";

import { InsightsSection } from "@/components/me/InsightsSection";
import { PresetsSection } from "@/components/me/PresetsSection";
import { ReferralSection } from "@/components/me/ReferralSection";
import { colors } from "@/components/me/theme";
import { isAbortError, me as fetchMe } from "@/lib/api";
import { useRegistryGroups } from "@/lib/nav/RegistryMenu";
import { useConfirmSignOut, useSession } from "@/src/shared/auth";
import { ProMembershipCard } from "@/src/shared/billing";
import { openLegalDocument } from "@/src/shared/legal/open-legal";
import { Icon, type IconName } from "@/components/ui/Icon";
import { isRouteAvailable } from "@/src/shared/release/surface";
import { ListRow } from "@/components/ui/ListRow";

interface EssentialLink {
  readonly title: string;
  readonly subtitle: string;
  readonly icon: IconName;
  readonly route: string;
}

/**
 * Fixed, always-visible account essentials. Everything else lives one tap away
 * in the grouped directory below (and the searchable navigation hub), so the
 * Me tab stays short instead of listing every registered screen.
 */
const ESSENTIALS: readonly EssentialLink[] = [
  { title: "Wallet & credits", subtitle: "Balance, credit packs, history and plans", icon: "wallet-outline", route: "/wallet" },
  { title: "Creator Contract", subtitle: "Credits never expire, failed renders refunded, no training on you", icon: "ribbon-outline", route: "/legal/creator-contract" },
  { title: "Drafts", subtitle: "Ideas and scripts saved for later", icon: "albums-outline", route: "/drafts" },
  { title: "Uploads", subtitle: "Your clips, images and audio", icon: "cloud-upload-outline", route: "/uploads" },
  { title: "Notifications", subtitle: "Render, publish and account updates", icon: "notifications-outline", route: "/notifications" },
  { title: "Account settings", subtitle: "Profile, subscription and account deletion", icon: "person-circle-outline", route: "/account/settings" },
  { title: "Privacy & data", subtitle: "Export your data, consent and erasure", icon: "shield-checkmark-outline", route: "/privacy" },
  { title: "Support", subtitle: "Help with a job, export, purchase or account", icon: "help-buoy-outline", route: "/support" },
];

/**
 * Profile / Me tab. Three independently-loading, caller-scoped growth surfaces:
 * INSIGHTS (stat cards), REFERRAL (code + share + redeem) and PRESETS (saved
 * kit CRUD). Each section owns its own fetch + loading/error state so a failure
 * in one never blanks the others. Auth token comes from the session (sent as
 * `x-api-key` by the shared api client).
 */
export default function MeScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const confirmSignOut = useConfirmSignOut();
  const groups = useRegistryGroups().filter((group) => group.name !== "Navigation");
  const token = apiKey ?? undefined;

  // The caller's own id, used to deep-link to their PUBLIC creator profile
  // (GET /creators/{handle_or_id} accepts a user id). Fetched best-effort; the
  // profile link stays disabled until it resolves.
  const [myUserId, setMyUserId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchMe({ token, signal: controller.signal })
      .then((profile) => setMyUserId(profile.user_id || null))
      .catch((err: unknown) => {
        if (!isAbortError(err)) setMyUserId(null);
      });
    return () => controller.abort();
  }, [token]);

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <InsightsSection token={token} />

      <ProMembershipCard />

      {/* Searchable directory of every screen: dev sessions only. */}
      {isRouteAvailable("/navigation/discoverability") ? (
        <Pressable
          style={styles.hubLink}
          onPress={() => router.push("/navigation/discoverability")}
          accessibilityRole="button"
        >
          <View style={styles.linkBody}>
            <Text style={styles.linkTitle}>Explore all screens</Text>
            <Text style={styles.linkSubtitle}>Dev session: every studio, lab and setting</Text>
          </View>
          <Icon name="chevron-forward" style={styles.linkChevron} />
        </Pressable>
      ) : null}

      <Text style={styles.sectionLabel}>Account</Text>
      <View style={styles.section}>
        {ESSENTIALS.filter((link) => isRouteAvailable(link.route)).map((link) => (
          <ListRow
            key={link.route}
            title={link.title}
            subtitle={link.subtitle}
            leading={<Icon name={link.icon} size={20} color={colors.textSecondary} />}
            onPress={() => router.push(link.route as Parameters<typeof router.push>[0])}
          />
        ))}
      </View>

      {/* Registry groups — one row per group, opening that group's directory. */}
      <Text style={styles.sectionLabel}>Tools</Text>
      <View style={styles.section}>
        {groups.map((group) => (
          <ListRow
            key={group.name}
            title={group.name}
            subtitle={group.screens
              .slice(0, 3)
              .map((screen) => screen.title)
              .join(", ")
              .concat(group.screens.length > 3 ? ` and ${group.screens.length - 3} more` : "")}
            onPress={() =>
              router.push(
                `/navigation/discoverability/${encodeURIComponent(group.name)}` as Parameters<
                  typeof router.push
                >[0],
              )
            }
          />
        ))}
      </View>

      {/* Creator profile — needs dynamic user id, resolved via /me */}
      {isRouteAvailable("/creator/me") ? (
      <Pressable
        style={[styles.link, !myUserId && styles.linkDisabled]}
        disabled={!myUserId}
        onPress={() => {
          if (myUserId) router.push(`/creator/${myUserId}`);
        }}
      >
        <View style={styles.linkBody}>
          <Text style={styles.linkTitle}>My creator profile</Text>
          <Text style={styles.linkSubtitle}>
            View your public profile, followers and published templates
          </Text>
        </View>
        <Icon name="chevron-forward" style={styles.linkChevron} />
      </Pressable>
      ) : null}

      {isRouteAvailable("/insights/referral") ? <ReferralSection token={token} /> : null}
      <PresetsSection token={token} />

      <View style={styles.legalRow}>
        <Pressable
          onPress={() => openLegalDocument("terms", router)}
          accessibilityRole="link"
          hitSlop={8}
        >
          <Text style={styles.legalLink}>Terms of Service</Text>
        </Pressable>
        <Pressable
          onPress={() => openLegalDocument("privacy", router)}
          accessibilityRole="link"
          hitSlop={8}
        >
          <Text style={styles.legalLink}>Privacy Policy</Text>
        </Pressable>
        <Pressable
          onPress={() => openLegalDocument("contract", router)}
          accessibilityRole="link"
          hitSlop={8}
        >
          <Text style={styles.legalLink}>Creator Contract</Text>
        </Pressable>
      </View>

      <Pressable style={styles.signOut} onPress={confirmSignOut} accessibilityRole="button">
        <Text style={styles.signOutText}>Sign out</Text>
      </Pressable>
      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 24 },
  link: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    marginBottom: 28,
  },
  hubLink: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: colors.card,
    borderColor: colors.accent,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    marginBottom: 20,
  },
  linkDisabled: { opacity: 0.5 },
  linkBody: { flex: 1, gap: 4 },
  linkTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  linkSubtitle: { color: colors.muted, fontSize: 12 },
  linkChevron: { color: colors.muted, fontSize: 22, fontWeight: "700" },
  signOut: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 4,
  },
  signOutText: { color: colors.textSecondary, fontWeight: "600", fontSize: 15 },
  spacer: { height: 40 },
  sectionLabel: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1.2,
    textTransform: "uppercase",
    marginBottom: 8,
    paddingLeft: 2,
  },
  section: { gap: 8, marginBottom: 24 },
  legalRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "center",
    gap: 20,
    marginBottom: 16,
  },
  legalLink: {
    color: colors.textSecondary,
    fontSize: 13,
    fontWeight: "600",
    textDecorationLine: "underline",
  },
});
