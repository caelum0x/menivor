/**
 * Route: /library — Library & Studio hub.
 *
 * A single discoverable index for the browse/reference and management surfaces
 * that don't belong in the primary create flow: the creative Catalog (caption
 * styles, music, layouts, templates, hooks, cover styles, dub languages), the
 * Studio galleries (avatars, voices), the Reels library, the Wallet & billing
 * cluster, growth Insights, social Connections and Account settings.
 *
 * Entries are grouped and labelled (no emoji — section headers + chevrons only)
 * and each deep-links to its screen. Reached from the Me tab.
 */

import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { useRouter } from "expo-router";

import { colors } from "@/components/me/theme";
import { Icon } from "@/components/ui/Icon";

interface HubLink {
  title: string;
  subtitle: string;
  route: string;
}

interface HubSection {
  heading: string;
  caption: string;
  links: readonly HubLink[];
}

const SECTIONS: readonly HubSection[] = [
  {
    heading: "Catalog",
    caption: "Browse the creative building blocks you can drop into a reel.",
    links: [
      { title: "Catalog", subtitle: "Every creative preset in one place", route: "/catalog" },
      { title: "Reddit Story", subtitle: "Turn a Reddit thread URL into a narrated reel draft", route: "/catalog/reddit-story" },
      { title: "Model Catalog", subtitle: "Compare reviewed models by price and health", route: "/catalog/model-catalog" },
      { title: "Provider Health", subtitle: "Live uptime and latency per generation provider", route: "/catalog/provider-health" },
      { title: "Estimate Cost", subtitle: "Price your model choices with a signed quote", route: "/catalog/quote" },
      { title: "Motion & VFX", subtitle: "Camera moves and stackable cinematic effects", route: "/catalog/presets" },
      { title: "Caption Styles", subtitle: "Preview the burned-in caption looks", route: "/catalog/caption-styles" },
      { title: "Music Library", subtitle: "Licensed background tracks by mood", route: "/catalog/music" },
      { title: "Layouts", subtitle: "Split, PIP, full-bleed and captions-only", route: "/catalog/layouts" },
      { title: "Templates", subtitle: "One-tap viral formats to start from", route: "/catalog/templates" },
      { title: "Hook Lines", subtitle: "Proven first-3s openers by genre", route: "/catalog/hooks" },
      { title: "Cover Styles", subtitle: "Thumbnail / cover frame presets", route: "/catalog/cover-styles" },
      { title: "Dub Languages", subtitle: "Languages you can auto-dub into", route: "/catalog/dub-languages" },
    ],
  },
  {
    heading: "Studio",
    caption: "Your avatars, narrators and identity-locked creative tools.",
    links: [
      { title: "Avatar Gallery", subtitle: "Browse and open your talking-photo avatars", route: "/studio/avatars" },
      { title: "Voice Library", subtitle: "Catalog narrators you can pick from", route: "/studio/voices" },
      { title: "My Voices", subtitle: "Your cloned voices and their status", route: "/account/voices" },
      { title: "Caption Studio", subtitle: "Hook score, punch captions, safe zones, loop check, beat fit, SEO", route: "/studio/captions" },
      { title: "Character Canon", subtitle: "Lock canonical brand/character identities and versions", route: "/studio/characters/canon" },
      { title: "Motion Presets", subtitle: "The versioned camera-move catalog you can compile", route: "/studio/motion" },
      { title: "Design Studio", subtitle: "Posts, stories and banners in your brand", route: "/studio/design" },
      { title: "Dub a Video", subtitle: "Dub any uploaded video into another language", route: "/studio/dub" },
    ],
  },
  {
    heading: "Content Engine",
    caption: "Turn long recordings and URLs into AI-scored vertical shorts.",
    links: [
      { title: "Content Engine", subtitle: "Repurpose or auto-clip a long recording into shorts", route: "/repurpose/clipping" },
      { title: "Import from URL", subtitle: "Paste a product or article URL to draft a reel", route: "/repurpose/clipping/ingest" },
    ],
  },
  {
    heading: "Reels",
    caption: "Your finished and scheduled reels.",
    links: [
      { title: "Reels", subtitle: "Your rendered reels library", route: "/(tabs)/jobs" },
      { title: "Schedule", subtitle: "Queued auto-publishes and posting slots", route: "/scheduled" },
      { title: "Uploads", subtitle: "Source clips, images and audio you uploaded", route: "/uploads" },
      { title: "Social Inbox", subtitle: "Comments and messages on your published posts", route: "/inbox" },
      { title: "Render history", subtitle: "Every GPU render with playable outputs", route: "/render" },
      { title: "Film projects", subtitle: "Saved multi-shot films, shot renders and final export", route: "/film" },
    ],
  },
  {
    heading: "Wallet & Billing",
    caption: "Balance, top-ups, transfers, plans and invoices.",
    links: [
      { title: "Wallet", subtitle: "Live balance, spend and quick actions", route: "/wallet" },
      { title: "Transactions", subtitle: "Full wallet ledger", route: "/wallet/history" },
      { title: "Add credit", subtitle: "Top up your USD balance", route: "/wallet/top-up" },
      { title: "Send tokens", subtitle: "Transfer credit to another handle", route: "/wallet/transfer" },
      { title: "Send limits", subtitle: "Per-transfer and daily send guardrails", route: "/wallet/transfer-policy" },
      { title: "Plans", subtitle: "Compare and change subscription tiers", route: "/wallet/plans" },
      { title: "Billing history", subtitle: "Invoices and usage statements", route: "/wallet/billing-history" },
    ],
  },
  {
    heading: "Insights",
    caption: "Growth surfaces: stats, referrals and saved presets.",
    links: [
      { title: "Insights", subtitle: "Your creator stats at a glance", route: "/insights" },
      { title: "Referral Program", subtitle: "Share your code and redeem credit", route: "/insights/referral" },
      { title: "Reel Presets", subtitle: "Saved kits you can reapply", route: "/insights/presets" },
    ],
  },
  {
    heading: "Connections",
    caption: "Link platforms and publish or draft social copy.",
    links: [
      { title: "Connected Accounts", subtitle: "Link TikTok, Instagram and YouTube", route: "/connections/manage" },
      { title: "Publish a Reel", subtitle: "Post a finished reel to a platform", route: "/connections/publish" },
      { title: "AI Social Copy", subtitle: "Draft captions and hashtags per platform", route: "/connections/social-copy" },
      { title: "Draft Social Copy", subtitle: "Generate title, caption and hashtags before a reel exists", route: "/connections/social-metadata" },
    ],
  },
  {
    heading: "Account",
    caption: "Workspaces, preferences and developer access.",
    links: [
      { title: "Workspaces", subtitle: "Switch, create and manage workspaces", route: "/account/workspaces" },
      { title: "Account & Settings", subtitle: "Profile, preferences and security", route: "/account/settings" },
      { title: "Developer & API Keys", subtitle: "Personal keys for the REST API", route: "/account/developer-keys" },
      { title: "Provider Keys (BYOK)", subtitle: "Store your own provider keys for BYOK renders", route: "/account/provider-keys" },
    ],
  },
];

export default function LibraryHubScreen() {
  const router = useRouter();

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      {SECTIONS.map((section) => (
        <View key={section.heading} style={styles.section}>
          <Text style={styles.sectionHeading}>{section.heading}</Text>
          <Text style={styles.sectionCaption}>{section.caption}</Text>
          {section.links.map((link) => (
            <Pressable
              key={link.route}
              style={styles.link}
              accessibilityRole="button"
              accessibilityLabel={link.title}
              onPress={() => router.push(link.route as never)}
            >
              <View style={styles.linkBody}>
                <Text style={styles.linkTitle}>{link.title}</Text>
                <Text style={styles.linkSubtitle}>{link.subtitle}</Text>
              </View>
              <Icon name="chevron-forward" style={styles.linkChevron} />
            </Pressable>
          ))}
        </View>
      ))}
      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 24 },
  section: { marginBottom: 28 },
  sectionHeading: {
    color: colors.textPrimary,
    fontSize: 18,
    fontWeight: "800",
    letterSpacing: 0.2,
  },
  sectionCaption: {
    color: colors.muted,
    fontSize: 12,
    marginTop: 4,
    marginBottom: 12,
  },
  link: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    marginBottom: 10,
  },
  linkBody: { flex: 1, gap: 4 },
  linkTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  linkSubtitle: { color: colors.muted, fontSize: 12 },
  linkChevron: { color: colors.muted, fontSize: 22, fontWeight: "700" },
  spacer: { height: 40 },
});
