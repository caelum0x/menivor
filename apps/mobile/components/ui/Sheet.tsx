/**
 * Sheet primitive — a bottom sheet modal.
 * Uses React Native's Modal positioned at the bottom.
 * No emoji. Explicit types.
 */

import type { ReactNode } from "react";
import {
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { colors } from "@/components/me/theme";
import { radius, spacing, weight } from "@/src/shared/theme";

export interface SheetProps {
  visible: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  /** Maximum height expressed as a fraction of screen height (0..1). */
  maxHeightFraction?: number;
  style?: StyleProp<ViewStyle>;
}

export function Sheet({
  visible,
  onClose,
  title,
  children,
  maxHeightFraction = 0.75,
  style,
}: SheetProps): React.JSX.Element {
  const insets = useSafeAreaInsets();

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
      statusBarTranslucent
    >
      {/* Backdrop */}
      <Pressable style={styles.backdrop} onPress={onClose} />

      {/* Sheet panel */}
      <View
        style={[
          styles.panel,
          {
            paddingBottom: insets.bottom + spacing.lg,
            maxHeight: `${Math.round(maxHeightFraction * 100)}%`,
          },
          style,
        ]}
      >
        {/* Drag handle */}
        <View style={styles.handleRow}>
          <View style={styles.handle} />
        </View>

        {title ? (
          <View style={styles.titleRow}>
            <Text style={styles.title}>{title}</Text>
            <Pressable
              onPress={onClose}
              accessibilityRole="button"
              accessibilityLabel="Close"
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
            >
              <Text style={styles.closeBtn}>{"Done"}</Text>
            </Pressable>
          </View>
        ) : null}

        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          {children}
        </ScrollView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0,0,0,0.6)",
  },
  panel: {
    position: "absolute",
    bottom: 0,
    left: 0,
    right: 0,
    backgroundColor: colors.card,
    borderTopLeftRadius: radius.lg * 2,
    borderTopRightRadius: radius.lg * 2,
    borderTopWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
  },
  handleRow: { alignItems: "center", paddingTop: spacing.md, paddingBottom: spacing.sm },
  handle: {
    width: 36,
    height: 4,
    borderRadius: radius.pill,
    backgroundColor: colors.border,
  },
  titleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  title: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: weight.bold,
  },
  closeBtn: {
    color: colors.accent,
    fontSize: 15,
    fontWeight: weight.semibold,
  },
  content: {
    padding: spacing.lg,
    gap: spacing.md,
  },
});
