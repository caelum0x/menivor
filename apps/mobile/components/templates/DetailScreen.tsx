/**
 * DetailScreen template — hero section + sections + action bar.
 *
 * Handles the common pattern: full-bleed hero image/content at top,
 * then a scrollable body of labelled sections, and a sticky action row at bottom.
 *
 * Usage (a typical detail screen becomes ~40-60 lines):
 * ```tsx
 * <DetailScreen
 *   hero={<JobPoster jobId={id} />}
 *   title={job.hook}
 *   subtitle={`State: ${job.state}`}
 *   sections={[
 *     { title: "Details", content: <JobDetailsCard job={job} /> },
 *     { title: "Actions", content: <JobActionsCard job={job} /> },
 *   ]}
 *   actions={[
 *     <Button label="Download" onPress={handleDownload} />,
 *     <Button label="Retry" variant="secondary" onPress={handleRetry} />,
 *   ]}
 * />
 * ```
 */

import type { ReactNode } from "react";
import {
  ScrollView,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { colors } from "@/components/me/theme";
import { radius, spacing, typeScale, weight } from "@/src/shared/theme";

export interface DetailSection {
  title?: string;
  content: ReactNode;
}

export interface DetailScreenProps {
  /** Full-bleed hero element (image, video poster, colored block). */
  hero?: ReactNode;
  title: string;
  subtitle?: string;
  /** Sections rendered beneath the title. */
  sections?: readonly DetailSection[];
  /** Action buttons rendered in a sticky footer. */
  actions?: readonly ReactNode[];
  style?: StyleProp<ViewStyle>;
}

export function DetailScreen({
  hero,
  title,
  subtitle,
  sections = [],
  actions = [],
  style,
}: DetailScreenProps): React.JSX.Element {
  const insets = useSafeAreaInsets();

  return (
    <View style={[styles.container, style]}>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={{ paddingBottom: actions.length ? 0 : spacing.xxl }}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        {/* Hero */}
        {hero ? <View style={styles.hero}>{hero}</View> : null}

        {/* Title */}
        <View style={styles.titleBlock}>
          <Text style={styles.title}>{title}</Text>
          {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
        </View>

        {/* Sections */}
        {sections.map((section, i) => (
          <View key={i} style={styles.section}>
            {section.title ? (
              <Text style={styles.sectionTitle}>{section.title}</Text>
            ) : null}
            {section.content}
          </View>
        ))}
      </ScrollView>

      {/* Sticky action bar */}
      {actions.length > 0 ? (
        <View
          style={[
            styles.actionBar,
            { paddingBottom: insets.bottom + spacing.md },
          ]}
        >
          {actions.map((action, i) => (
            <View key={i} style={styles.actionItem}>
              {action}
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  scroll: { flex: 1 },
  hero: {
    width: "100%",
    backgroundColor: colors.cardAlt,
  },
  titleBlock: {
    padding: spacing.lg,
    gap: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  title: {
    color: colors.textPrimary,
    fontSize: typeScale.heading,
    fontWeight: weight.black,
  },
  subtitle: {
    color: colors.textSecondary,
    fontSize: 13,
  },
  section: {
    padding: spacing.lg,
    gap: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  sectionTitle: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: weight.bold,
    letterSpacing: 1,
    textTransform: "uppercase",
  },
  actionBar: {
    flexDirection: "row",
    gap: spacing.sm,
    padding: spacing.md,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.bg,
  },
  actionItem: { flex: 1 },
});
