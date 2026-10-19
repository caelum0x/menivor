/**
 * One connected channel: status, what the inbox can read, and send-test /
 * re-check / disconnect actions. Tokens never come back from the API.
 */

import { Linking, Pressable, Text, View } from "react-native";

import { ActionButton } from "@/components/approvals/Button";
import { ui } from "@/components/approvals/styles";
import { channelStatusLabel, type Channel } from "@/lib/channels";

export interface RowNote {
  tone: "ok" | "error";
  text: string;
  url?: string;
}

export type ChannelAction = "verify" | "test" | "remove";

export interface ChannelRowProps {
  channel: Channel;
  busy: string | null;
  note?: RowNote;
  onAction: (id: string, action: ChannelAction) => void;
}

export function ChannelRow({ channel: c, busy, note, onAction }: Readonly<ChannelRowProps>) {
  const statusBad = c.status === "needs_reauth" || c.status === "error";
  return (
    <View style={ui.card} testID={`channel-${c.id}`}>
      <View style={ui.row}>
        <Text style={ui.title}>{c.label}</Text>
        <View style={ui.badge}>
          <Text style={ui.badgeText}>{c.kind_label}</Text>
        </View>
        <View style={[ui.badge, statusBad ? ui.badgeDanger : c.status === "connected" ? ui.badgeOk : null]}>
          <Text style={[ui.badgeText, statusBad ? ui.badgeDangerText : c.status === "connected" ? ui.badgeOkText : null]}>
            {channelStatusLabel(c.status)}
          </Text>
        </View>
        {c.shared ? (
          <View style={ui.badge}>
            <Text style={ui.badgeText}>Workspace</Text>
          </View>
        ) : null}
      </View>
      <Text style={ui.muted} numberOfLines={1}>{c.target_name}</Text>
      {c.public_url ? (
        <Pressable onPress={() => void Linking.openURL(c.public_url)} accessibilityRole="link">
          <Text style={[ui.muted, { textDecorationLine: "underline" }]}>Open channel</Text>
        </Pressable>
      ) : null}
      <Text style={ui.muted}>
        Inbox: {c.inbox.reads ? "reads replies" : "posting only"}. {c.inbox.note}
      </Text>
      {c.last_error ? <Text style={ui.error}>{c.last_error}</Text> : null}

      <View style={ui.row}>
        <ActionButton
          label="Send test"
          variant="ghost"
          icon="paper-plane-outline"
          onPress={() => onAction(c.id, "test")}
          busy={busy === `test:${c.id}`}
          disabled={!c.can_post || busy !== null}
        />
        {c.can_manage ? (
          <>
            <ActionButton
              label="Re-check"
              variant="ghost"
              icon="refresh"
              onPress={() => onAction(c.id, "verify")}
              busy={busy === `verify:${c.id}`}
              disabled={busy !== null}
            />
            <ActionButton
              label="Disconnect"
              variant="ghost"
              icon="trash-outline"
              accessibilityLabel={`Disconnect ${c.label}`}
              onPress={() => onAction(c.id, "remove")}
              busy={busy === `remove:${c.id}`}
              disabled={busy !== null}
            />
          </>
        ) : null}
      </View>
      {note ? (
        <View style={ui.row}>
          <Text style={note.tone === "ok" ? ui.ok : ui.error}>{note.text}</Text>
          {note.url ? (
            <Pressable onPress={() => void Linking.openURL(note.url ?? "")} accessibilityRole="link">
              <Text style={[ui.muted, { textDecorationLine: "underline" }]}>View it</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}
