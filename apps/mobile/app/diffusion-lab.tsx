import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";

import { colors } from "@/components/me/theme";
import { forecastDiffusion, type DiffusionContentType, type DiffusionForecast } from "@/lib/diffusion";
import { useSession } from "@/src/shared/auth";

const FIELDS = [
  ["directAudience", "Direct audience", "People normally reached first"],
  ["peerAudience", "Peer audiences", "Potential reach through shares"],
  ["nicheAudience", "Niche discovery pool", "Relevant audience outside your graph"],
  ["hookStrength", "Hook strength (%)", "Your measured or planned hook score"],
  ["shareRate", "Share rate (%)", "Expected share probability per audience layer"],
] as const;

const CONTENT_TYPES: Array<{ id: DiffusionContentType; label: string }> = [
  { id: "short_video", label: "Short video" },
  { id: "tutorial", label: "Tutorial" },
  { id: "product_demo", label: "Product demo" },
  { id: "commentary", label: "Commentary" },
];

export default function DiffusionLabScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const params = useLocalSearchParams<{
    observation_id?: string | string[];
    trend_id?: string | string[];
    subject?: string | string[];
  }>();
  const observationId = Array.isArray(params.observation_id) ? params.observation_id[0] : params.observation_id;
  const trendId = Array.isArray(params.trend_id) ? params.trend_id[0] : params.trend_id;
  const trendLabel = Array.isArray(params.subject) ? params.subject[0] : params.subject;
  const [values, setValues] = useState<Record<(typeof FIELDS)[number][0], string>>({
    directAudience: "", peerAudience: "", nicheAudience: "", hookStrength: "", shareRate: "",
  });
  const [result, setResult] = useState<DiffusionForecast | null>(null);
  const [contentType, setContentType] = useState<DiffusionContentType>("short_video");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function calculate() {
    if (!observationId) {
      setError("Choose a durable trend observation from the trends feed first.");
      return;
    }
    const input = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, Number(value)])) as Record<keyof typeof values, number>;
    if (Object.values(input).some((value) => !Number.isFinite(value) || value < 0)) {
      setError("Enter a non-negative number in every field.");
      return;
    }
    setBusy(true); setError("");
    try {
      setResult(await forecastDiffusion(
        { ...input, trendObservationId: observationId, contentType },
        { token: apiKey ?? undefined },
      ));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Forecast failed.");
    } finally { setBusy(false); }
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.title}>Diffusion planner</Text>
      <Text style={styles.intro}>Estimate how a short video may move from your direct audience into peer and niche audiences. Every number below is your planning assumption.</Text>
      <View style={styles.sourceCard}>
        <Text style={styles.sourceLabel}>Trend source</Text>
        <Text style={styles.sourceValue}>{trendLabel || trendId || "No trend selected"}</Text>
        <Text style={styles.sourceMeta}>{observationId ? `Observation ${observationId}` : "Open this planner from a saved trend in the feed."}</Text>
      </View>
      <View style={styles.form}>
        <View style={styles.field}>
          <Text style={styles.label}>Content type</Text>
          <View style={styles.typeRow}>
            {CONTENT_TYPES.map((option) => (
              <Pressable
                key={option.id}
                style={[styles.typeChoice, contentType === option.id && styles.typeChoiceActive]}
                onPress={() => setContentType(option.id)}
              >
                <Text style={[styles.typeText, contentType === option.id && styles.typeTextActive]}>{option.label}</Text>
              </Pressable>
            ))}
          </View>
        </View>
        {FIELDS.map(([key, label, help]) => (
          <View key={key} style={styles.field}>
            <Text style={styles.label}>{label}</Text><Text style={styles.help}>{help}</Text>
            <TextInput style={styles.input} keyboardType="numeric" value={values[key]} onChangeText={(value) => setValues({ ...values, [key]: value })} placeholder="Enter value" placeholderTextColor={colors.muted} />
          </View>
        ))}
        <Pressable style={styles.button} onPress={() => void calculate()} disabled={busy}>
          {busy ? <ActivityIndicator color={colors.bg} /> : <Text style={styles.buttonText}>Calculate forecast</Text>}
        </Pressable>
        {error ? <Text style={styles.error}>{error}</Text> : null}
      </View>
      {result ? (
        <View style={styles.result}>
          <Text style={styles.resultLabel}>Expected reach after {result.steps} steps</Text>
          <Text style={styles.reach}>{result.expected_reach.toLocaleString()}</Text>
          <Text style={styles.fraction}>{Math.round(result.adoption_fraction * 100)}% of submitted audience</Text>
          <Text style={styles.forecastId}>Forecast {result.forecast_id}</Text>
          <View style={styles.timeline}>{result.timeline.map((point) => <View key={point.step} style={styles.step}><Text style={styles.stepLabel}>Step {point.step}</Text><View style={[styles.bar, { width: `${Math.max(2, point.expected_reach / Math.max(1, result.expected_reach) * 100)}%` }]} /><Text style={styles.stepValue}>{point.expected_reach.toLocaleString()}</Text></View>)}</View>
          <Text style={styles.notice}>{result.assumption_notice}</Text>
          <Pressable
            style={styles.composeButton}
            onPress={() => router.push({
              pathname: "/compose",
              params: {
                forecast_id: result.forecast_id,
                trend_id: result.trend.trend_id,
                subject: result.trend.label || result.trend.trend_id,
              },
            })}
          >
            <Text style={styles.composeButtonText}>Create from this forecast</Text>
          </Pressable>
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container:{flex:1,backgroundColor:colors.bg},content:{padding:18,paddingBottom:42},title:{color:colors.textPrimary,fontSize:34,fontWeight:"800",letterSpacing:-1.2},intro:{color:colors.textSecondary,fontSize:14,lineHeight:21,marginTop:10,marginBottom:14},sourceCard:{padding:14,backgroundColor:colors.card,borderWidth:1,borderColor:colors.primary,borderRadius:12,marginBottom:20,gap:4},sourceLabel:{color:colors.muted,fontSize:11,fontWeight:"700"},sourceValue:{color:colors.textPrimary,fontSize:16,fontWeight:"800"},sourceMeta:{color:colors.textSecondary,fontSize:11},form:{gap:14},field:{padding:14,backgroundColor:colors.card,borderWidth:1,borderColor:colors.border,borderRadius:12},label:{color:colors.textPrimary,fontSize:14,fontWeight:"700"},help:{color:colors.muted,fontSize:11,marginTop:3},input:{color:colors.textPrimary,borderBottomWidth:1,borderBottomColor:colors.border,paddingVertical:9,marginTop:8},typeRow:{flexDirection:"row",flexWrap:"wrap",gap:8,marginTop:10},typeChoice:{borderWidth:1,borderColor:colors.border,borderRadius:8,paddingHorizontal:10,paddingVertical:8},typeChoiceActive:{borderColor:colors.primary,backgroundColor:colors.cardAlt},typeText:{color:colors.textSecondary,fontSize:12},typeTextActive:{color:colors.textPrimary,fontWeight:"700"},button:{minHeight:50,alignItems:"center",justifyContent:"center",backgroundColor:colors.primary,borderRadius:12},buttonText:{color:colors.bg,fontSize:15,fontWeight:"800"},error:{color:colors.error,fontSize:13},result:{marginTop:24,padding:18,backgroundColor:colors.card,borderWidth:1,borderColor:colors.primary,borderRadius:16},resultLabel:{color:colors.textSecondary,fontSize:12},reach:{color:colors.textPrimary,fontSize:52,fontWeight:"800",letterSpacing:-2,marginTop:6},fraction:{color:colors.primary,fontSize:13,fontWeight:"700"},forecastId:{color:colors.muted,fontSize:11,marginTop:5},timeline:{gap:12,marginTop:24},step:{position:"relative",minHeight:34,justifyContent:"center",overflow:"hidden",borderRadius:7,backgroundColor:colors.bg},bar:{position:"absolute",left:0,top:0,bottom:0,backgroundColor:colors.primary,opacity:.35},stepLabel:{color:colors.textSecondary,fontSize:11,marginLeft:9,zIndex:1},stepValue:{position:"absolute",right:9,color:colors.textPrimary,fontSize:12,fontWeight:"700"},notice:{color:colors.muted,fontSize:11,lineHeight:17,marginTop:20},composeButton:{marginTop:16,minHeight:46,alignItems:"center",justifyContent:"center",borderRadius:10,backgroundColor:colors.primary},composeButtonText:{color:colors.textPrimary,fontSize:14,fontWeight:"800"},
});
