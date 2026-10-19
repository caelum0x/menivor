/**
 * Connect a Telegram channel/group, a Discord channel webhook or a Mastodon
 * account. The API verifies the credential before storing it (encrypted) and
 * never returns it. Mirrors apps/web/components/calendar/ConnectChannelForm.tsx.
 */

import { useState } from "react";
import { Linking, Pressable, Text, TextInput, View } from "react-native";

import { ActionButton } from "@/components/approvals/Button";
import { ui } from "@/components/approvals/styles";
import { colors } from "@/components/me/theme";
import {
  BLANK_FIELDS,
  CHANNEL_KINDS,
  connectChannel,
  connectReady,
  toConnectInput,
  type Channel,
  type ChannelKind,
  type ChannelKindInfo,
  type ConnectFields,
  type MastodonVisibility,
} from "@/lib/channels";
import { readableApiError } from "@/lib/readable-error";

export interface ConnectChannelFormProps {
  kinds: readonly ChannelKindInfo[];
  token?: string;
  onConnected: (channel: Channel) => void;
}

const FALLBACK_LABELS: Record<ChannelKind, string> = {
  telegram: "Telegram",
  discord: "Discord",
  mastodon: "Mastodon",
};

const VISIBILITIES: readonly { value: MastodonVisibility; label: string }[] = [
  { value: "public", label: "Public" },
  { value: "unlisted", label: "Unlisted" },
  { value: "private", label: "Followers only" },
];

function Field({
  label,
  value,
  onChange,
  placeholder,
  secret,
  hint,
}: Readonly<{
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  secret?: boolean;
  hint?: string;
}>) {
  return (
    <View style={{ gap: 4 }}>
      <Text style={ui.kicker}>{label}</Text>
      <TextInput
        style={ui.input}
        value={value}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={colors.muted}
        secureTextEntry={secret}
        autoCapitalize="none"
        autoCorrect={false}
        accessibilityLabel={label}
      />
      {hint ? <Text style={ui.muted}>{hint}</Text> : null}
    </View>
  );
}

export function ConnectChannelForm({ kinds, token, onConnected }: Readonly<ConnectChannelFormProps>) {
  const [kind, setKind] = useState<ChannelKind>("telegram");
  const [fields, setFields] = useState<Record<ChannelKind, ConnectFields>>({
    telegram: BLANK_FIELDS,
    discord: BLANK_FIELDS,
    mastodon: BLANK_FIELDS,
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const info = kinds.find((k) => k.kind === kind);
  const f = fields[kind];
  const set = (key: keyof ConnectFields) => (value: string) =>
    setFields((prev) => ({ ...prev, [kind]: { ...prev[kind], [key]: value } }));

  const submit = async () => {
    setSubmitting(true);
    setError("");
    setDone("");
    try {
      const channel = await connectChannel(toConnectInput(kind, f), { token });
      onConnected(channel);
      setFields((prev) => ({ ...prev, [kind]: BLANK_FIELDS }));
      setDone(`${channel.label} is connected. Send a test post to check it end to end.`);
    } catch (err) {
      setError(readableApiError(err, "Couldn't connect this channel."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View style={ui.card}>
      <View style={ui.row} accessibilityRole="tablist">
        {CHANNEL_KINDS.map((k) => {
          const selected = k === kind;
          return (
            <Pressable
              key={k}
              onPress={() => {
                setKind(k);
                setError("");
                setDone("");
              }}
              style={[ui.chip, selected && ui.chipOn]}
              accessibilityRole="tab"
              accessibilityState={{ selected }}
            >
              <Text style={[ui.chipText, selected && ui.chipTextOn]}>
                {kinds.find((x) => x.kind === k)?.label ?? FALLBACK_LABELS[k]}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {info ? (
        <View style={{ gap: 4 }}>
          <Text style={ui.body}>{info.help}</Text>
          <Text style={ui.muted}>{info.cost_note}</Text>
          {info.docs_url ? (
            <Pressable onPress={() => void Linking.openURL(info.docs_url)} accessibilityRole="link">
              <Text style={[ui.muted, { textDecorationLine: "underline" }]}>API docs</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}

      {kind === "telegram" ? (
        <>
          <Field label="Bot token" value={f.bot_token} onChange={set("bot_token")} secret
            placeholder="123456789:AA..." hint="From @BotFather. Stored encrypted." />
          <Field label="Channel or group" value={f.chat_id} onChange={set("chat_id")}
            placeholder="@yourchannel or -1001234567890" />
        </>
      ) : null}
      {kind === "discord" ? (
        <>
          <Field label="Webhook URL" value={f.webhook_url} onChange={set("webhook_url")} secret
            placeholder="https://discord.com/api/webhooks/..." hint="Stored encrypted. Enough for posting." />
          <Field label="Bot token (optional)" value={f.bot_token} onChange={set("bot_token")} secret
            hint="Only needed to read replies in the inbox." />
          <Field label="Channel id (optional)" value={f.channel_id} onChange={set("channel_id")}
            placeholder="Defaults to the webhook's channel" />
        </>
      ) : null}
      {kind === "mastodon" ? (
        <>
          <Field label="Instance" value={f.instance} onChange={set("instance")} placeholder="mastodon.social" />
          <Field label="Access token" value={f.access_token} onChange={set("access_token")} secret
            hint="Scopes: read and write. Stored encrypted." />
          <Text style={ui.kicker}>Post visibility</Text>
          <View style={ui.row}>
            {VISIBILITIES.map((v) => {
              const selected = f.visibility === v.value;
              return (
                <Pressable
                  key={v.value}
                  onPress={() => set("visibility")(v.value)}
                  style={[ui.chip, selected && ui.chipOn]}
                  accessibilityRole="button"
                  accessibilityState={{ selected }}
                >
                  <Text style={[ui.chipText, selected && ui.chipTextOn]}>{v.label}</Text>
                </Pressable>
              );
            })}
          </View>
        </>
      ) : null}
      <Field label="Name in Menivor (optional)" value={f.label} onChange={set("label")}
        placeholder="For example: Puzzle game updates" />

      <ActionButton
        label={submitting ? "Checking" : "Connect"}
        icon="link"
        onPress={() => void submit()}
        busy={submitting}
        disabled={!connectReady(kind, f)}
      />
      {error ? <Text style={ui.error} accessibilityRole="alert">{error}</Text> : null}
      {done ? <Text style={ui.ok}>{done}</Text> : null}
    </View>
  );
}
