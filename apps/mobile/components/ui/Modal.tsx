/**
 * Modal primitive — a centered dialog overlay.
 * Uses React Native's Modal component. No emoji.
 */

import type { ReactNode } from "react";
import {
  Modal as RNModal,
  Pressable,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { colors } from "@/components/me/theme";
import { radius, spacing, weight } from "@/src/shared/theme";

export interface ModalProps {
  visible: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  /** Whether tapping the backdrop closes the modal. Defaults true. */
  closeOnBackdrop?: boolean;
}

export function Modal({
  visible,
  onClose,
  title,
  children,
  style,
  closeOnBackdrop = true,
}: ModalProps): React.JSX.Element {
  return (
    <RNModal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
      statusBarTranslucent
    >
      <Pressable
        style={styles.backdrop}
        onPress={closeOnBackdrop ? onClose : undefined}
      />
      <View style={styles.centeredContainer} pointerEvents="box-none">
        <View style={[styles.dialog, style]}>
          {title ? (
            <View style={styles.titleRow}>
              <Text style={styles.title}>{title}</Text>
              <Pressable
                onPress={onClose}
                accessibilityRole="button"
                accessibilityLabel="Close"
                hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
              >
                <Text style={styles.closeBtn}>{"x"}</Text>
              </Pressable>
            </View>
          ) : null}
          {children}
        </View>
      </View>
    </RNModal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0,0,0,0.65)",
  },
  centeredContainer: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
  },
  dialog: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.lg,
    width: "100%",
    maxWidth: 420,
    gap: spacing.md,
  },
  titleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  title: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: weight.bold,
  },
  closeBtn: {
    color: colors.muted,
    fontSize: 18,
    fontWeight: weight.bold,
  },
});
