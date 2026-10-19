/**
 * Platform-admin console (read-mostly).
 *
 * A lightweight mobile mirror of the internal/web admin surfaces. It is the hub
 * for the cross-tenant operator views — users, revenue, retention posture, every
 * job, every workspace, and the erasure-request queue — plus the two write
 * actions (impersonate + operator-initiated erasure) which live on the Users
 * screen behind explicit confirmation.
 *
 * EVERY endpoint behind these screens is HARD-GATED on the platform `is_staff`
 * flag SERVER-SIDE (a workspace owner is NOT staff). A non-staff caller gets a
 * 403 that each screen renders as a "platform-admin only" notice — the client
 * never grants access. This hub itself makes no privileged call; it only routes.
 *
 * NAV MANIFEST (for the integration agent to wire into navigation):
 *   - { route: "/account/admin", title: "Admin Console" }
 *   - { route: "/account/admin/users", title: "Users" }
 *   - { route: "/account/admin/revenue", title: "Revenue" }
 *   - { route: "/account/admin/retention", title: "Retention" }
 *   - { route: "/account/admin/jobs", title: "All Jobs" }
 *   - { route: "/account/admin/workspaces", title: "Workspaces" }
 *   - { route: "/account/admin/erasure-requests", title: "Erasure Requests" }
 */

import * as React from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { Stack, useRouter } from "expo-router";

import { colors } from "@/components/me/theme";
import { adminStyles } from "@/components/admin/ui";
import { Icon } from "@/components/ui/Icon";

interface AdminLink {
  route:
    | "/account/admin/users"
    | "/account/admin/revenue"
    | "/account/admin/retention"
    | "/account/admin/jobs"
    | "/account/admin/workspaces"
    | "/account/admin/erasure-requests";
  title: string;
  description: string;
}

const LINKS: readonly AdminLink[] = [
  {
    route: "/account/admin/users",
    title: "Users",
    description:
      "Every account across every tenant. Impersonate or erase a user (audited).",
  },
  {
    route: "/account/admin/revenue",
    title: "Revenue",
    description: "Platform-wide revenue, credits granted, and net (integer cents).",
  },
  {
    route: "/account/admin/retention",
    title: "Retention posture",
    description: "Every configured workspace data-retention window.",
  },
  {
    route: "/account/admin/jobs",
    title: "All jobs",
    description: "Cross-tenant job history with live state and progress.",
  },
  {
    route: "/account/admin/workspaces",
    title: "Workspaces",
    description: "Every workspace across every tenant, newest first.",
  },
  {
    route: "/account/admin/erasure-requests",
    title: "Erasure requests",
    description: "The cross-tenant right-to-erasure (GDPR Art. 17) queue.",
  },
];

export default function AdminConsoleScreen(): React.ReactElement {
  const router = useRouter();

  return (
    <ScrollView
      style={adminStyles.container}
      contentContainerStyle={adminStyles.content}
    >
      <Stack.Screen options={{ title: "Admin Console" }} />

      <Text style={adminStyles.intro}>
        Cross-tenant operator views. Access is restricted to platform staff; if
        your account is not staff, each surface shows a "platform-admin only"
        notice instead of any data.
      </Text>

      {LINKS.map((link) => (
        <Pressable
          key={link.route}
          style={styles.linkCard}
          onPress={() => router.push(link.route)}
          accessibilityRole="button"
          accessibilityLabel={link.title}
        >
          <View style={styles.linkTextWrap}>
            <Text style={styles.linkTitle}>{link.title}</Text>
            <Text style={styles.linkDescription}>{link.description}</Text>
          </View>
          <Icon name="chevron-forward" style={styles.chevron} />
        </Pressable>
      ))}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  linkCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  linkTextWrap: { flex: 1, gap: 4 },
  linkTitle: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  linkDescription: { color: colors.muted, fontSize: 13, lineHeight: 18 },
  chevron: { color: colors.muted, fontSize: 26, fontWeight: "300" },
  spacer: { height: 40 },
});
