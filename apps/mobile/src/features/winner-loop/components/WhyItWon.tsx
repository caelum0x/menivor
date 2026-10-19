/** Plain-language "why it won": metric comparisons, what differed, caveats. */

import { Text, View } from "react-native";

import { Badge, Icon } from "@/components/ui";
import { colors, radius, spacing } from "@/src/shared/theme";

import type { WinExplanation } from "../types";
import { sectionStyles as s } from "./styles";

export interface WhyItWonProps {
  readonly explanation: WinExplanation | null;
  readonly earlyRead: boolean;
  readonly hasWinner: boolean;
}

export function WhyItWon({ explanation, earlyRead, hasWinner }: WhyItWonProps) {
  return (
    <View style={s.card}>
      <View style={s.head}>
        <Icon name="bulb-outline" size={18} color={colors.accent} />
        <Text style={s.title}>{hasWinner ? "Why it won" : "Current leader"}</Text>
        {explanation && explanation.confidence !== "none" ? (
          <Badge
            label={explanation.confidence === "high" ? "High confidence" : "Low confidence"}
            variant={explanation.confidence === "high" ? "success" : "neutral"}
          />
        ) : null}
      </View>
      {earlyRead && !hasWinner ? (
        <Text style={s.micro}>Early read: the check window has not closed, so this can still change.</Text>
      ) : null}
      {!explanation ? (
        <Text style={s.muted}>
          The explanation appears after the first metrics check, once at least two variants have
          been live for the check window.
        </Text>
      ) : (
        <>
          <Text style={s.strong}>{explanation.headline}</Text>
          {explanation.reasons.slice(1).map((reason) => (
            <Text key={reason.metric} style={s.muted}>
              {"•"} {reason.text}
            </Text>
          ))}
          {explanation.differences.length > 0 ? (
            <View style={{ gap: spacing.xs }}>
              <Text style={s.label}>What was different</Text>
              {explanation.differences.map((diff) => (
                <View
                  key={diff.aspect}
                  style={{ backgroundColor: colors.surfaceAlt, borderRadius: radius.md, padding: spacing.sm, gap: 2 }}
                >
                  <Text style={s.body}>{diff.text}</Text>
                  {diff.aspect === "hook" ? (
                    <>
                      <Text style={s.micro}>Winner: {diff.winner}</Text>
                      {diff.others.map((other) => (
                        <Text key={other} style={s.micro}>
                          Other: {other}
                        </Text>
                      ))}
                    </>
                  ) : null}
                </View>
              ))}
            </View>
          ) : null}
          {explanation.caveats.map((caveat) => (
            <View key={caveat} style={s.row}>
              <Icon name="information-circle-outline" size={14} color={colors.textSecondary} />
              <Text style={[s.micro, { flex: 1 }]}>{caveat}</Text>
            </View>
          ))}
        </>
      )}
    </View>
  );
}
