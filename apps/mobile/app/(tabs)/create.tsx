/**
 * Create tab. Opens the one-flow create (topic or link -> 3 hook variants) by
 * default. Deep links that carry full-wizard params (Spark "Make this"
 * prefill, a saved draft, imported footage, an attached B-roll clip) open the
 * full editor in place so those flows keep working; a bar on top switches back
 * to the one-flow.
 */
import { Pressable, StyleSheet, Text, View } from "react-native";

import { useLocalSearchParams, useRouter } from "expo-router";

import { Icon } from "@/components/ui/Icon";
import { OneFlowCreateScreen } from "@/src/features/one-flow";
import { CreateScreen } from "@/src/features/reel-create";
import { colors, spacing, typeScale } from "@/src/shared/theme";

/** Route params that only the full wizard understands. */
const WIZARD_PARAMS = [
  "prefill",
  "subject",
  "script",
  "layout",
  "caption_style",
  "broll_key",
  "draft",
  "recording_key",
  "recording_name",
] as const;

type CreateTabParams = Partial<Record<(typeof WIZARD_PARAMS)[number] | "q" | "preset", string | string[]>>;

function first(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

export default function CreateTab() {
  const router = useRouter();
  const params = useLocalSearchParams<CreateTabParams>();
  const wantsWizard = WIZARD_PARAMS.some((key) => first(params[key]).trim() !== "");

  if (wantsWizard) {
    return (
      <View style={styles.fill}>
        <Pressable
          style={styles.switchBar}
          onPress={() =>
            // Clear the wizard params in place: navigating to the same tab
            // can keep the old params, which would reopen the full editor.
            router.setParams(
              Object.fromEntries(WIZARD_PARAMS.map((key) => [key, ""])) as Record<string, string>,
            )
          }
          accessibilityRole="button"
          accessibilityLabel="Switch to quick create, three hook variants"
        >
          <Text style={styles.switchText}>Full editor. Switch to quick create (3 hook variants)</Text>
          <Icon name="chevron-forward" size={16} color={colors.textSecondary} />
        </Pressable>
        <View style={styles.fill}>
          <CreateScreen />
        </View>
      </View>
    );
  }

  return (
    <OneFlowCreateScreen
      initialInput={first(params.q)}
      initialPreset={first(params.preset) || undefined}
    />
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: colors.bg },
  switchBar: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  switchText: { flex: 1, color: colors.textSecondary, fontSize: typeScale.caption, fontWeight: "600" },
});
