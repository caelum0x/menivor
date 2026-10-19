/**
 * One approval item with approve / edit / reject and an optional comment that
 * is stored as the decision note. Mirrors apps/web/app/approvals/_components/
 * ApprovalItemCard.tsx; post-scheduling items wait while publishing is closed.
 */

import { useState } from "react";
import { Text, TextInput, View } from "react-native";

import { colors } from "@/components/me/theme";
import {
  NOTE_MAX,
  PUBLISHING_SOURCES,
  SOURCE_LABELS,
  TEXT_MAX,
  approveBlocked,
  buildDecisionBody,
  canEditText,
  decideApproval,
  originalText,
  summarizeResult,
  type ApprovalItem,
  type Decision,
} from "@/lib/approvals";
import { readableApiError } from "@/lib/readable-error";

import { ActionButton } from "./Button";
import { ui } from "./styles";

export interface ApprovalCardProps {
  item: ApprovalItem;
  token?: string;
  /** Publishing launch gate; null while it is still loading. */
  publishingOpen: boolean | null;
  onDecided: (next: ApprovalItem) => void;
}

function formatWhen(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

function Badge({ label, tone }: Readonly<{ label: string; tone?: "danger" | "ok" }>) {
  return (
    <View style={[ui.badge, tone === "danger" && ui.badgeDanger, tone === "ok" && ui.badgeOk]}>
      <Text style={[ui.badgeText, tone === "danger" && ui.badgeDangerText, tone === "ok" && ui.badgeOkText]}>
        {label}
      </Text>
    </View>
  );
}

const DONE_STATUSES = new Set(["executed", "approved", "edited"]);

export function ApprovalCard({ item, token, publishingOpen, onDecided }: Readonly<ApprovalCardProps>) {
  const editable = canEditText(item);
  const [text, setText] = useState(originalText(item));
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState("");
  const [showNote, setShowNote] = useState(false);
  const [busy, setBusy] = useState<"" | Decision>("");
  const [error, setError] = useState("");

  const postsSomething = PUBLISHING_SOURCES.has(item.source);
  const gateLoading = postsSomething && publishingOpen === null;
  const blocked = gateLoading || approveBlocked(item, publishingOpen === true);
  const result = summarizeResult(item.result ?? {});

  const decide = async (decision: Decision) => {
    setBusy(decision);
    setError("");
    try {
      const body = buildDecisionBody(item, decision, note, editing ? text : null);
      const outcome = await decideApproval(item.id, decision, body, { token });
      setEditing(false);
      setShowNote(false);
      onDecided(outcome.item);
    } catch (err) {
      setError(readableApiError(err, "Couldn't record your decision. Try again."));
    } finally {
      setBusy("");
    }
  };

  return (
    <View style={ui.card} testID={`approval-${item.id}`}>
      <View style={ui.row}>
        <Badge label={SOURCE_LABELS[item.source] ?? item.source} />
        <Badge label={`${item.risk} risk`} tone={item.risk === "high" ? "danger" : undefined} />
        {item.status !== "pending" ? (
          <Badge
            label={item.status}
            tone={item.status === "failed" ? "danger" : DONE_STATUSES.has(item.status) ? "ok" : undefined}
          />
        ) : null}
      </View>
      <Text style={ui.title}>{item.title || "Untitled item"}</Text>
      {item.summary ? <Text style={ui.body}>{item.summary}</Text> : null}
      {item.created_at ? <Text style={ui.muted}>Queued {formatWhen(item.created_at)}</Text> : null}

      {editing ? (
        <View style={{ gap: 4 }}>
          <Text style={ui.kicker}>Text to send</Text>
          <TextInput
            style={[ui.input, ui.multiline]}
            value={text}
            onChangeText={setText}
            maxLength={TEXT_MAX}
            multiline
            editable={busy === ""}
            placeholderTextColor={colors.muted}
            accessibilityLabel="Text to send"
          />
        </View>
      ) : null}

      {showNote ? (
        <View style={{ gap: 4 }}>
          <Text style={ui.kicker}>Comment (saved with your decision)</Text>
          <TextInput
            style={[ui.input, ui.multiline]}
            value={note}
            onChangeText={setNote}
            maxLength={NOTE_MAX}
            multiline
            editable={busy === ""}
            placeholder="Why you approved or rejected this"
            placeholderTextColor={colors.muted}
            accessibilityLabel="Decision comment"
          />
        </View>
      ) : null}

      {item.error ? <Text style={ui.error}>{item.error}</Text> : null}

      {result ? (
        <View style={[ui.card, { backgroundColor: colors.cardAlt }]}>
          {result.posts.length ? <Text style={ui.kicker}>Queued posts</Text> : null}
          {result.posts.map((line) => (
            <Text key={line} style={ui.body}>{line}</Text>
          ))}
          {result.skipped.length ? <Text style={ui.kicker}>Not posted</Text> : null}
          {result.skipped.map((line) => (
            <Text key={line} style={ui.muted}>{line}</Text>
          ))}
          {result.jobIds.length ? <Text style={ui.kicker}>{result.jobsLabel}</Text> : null}
          {result.jobIds.length ? <Text style={ui.muted}>{result.jobIds.join(", ")}</Text> : null}
          {result.note ? <Text style={ui.muted}>{result.note}</Text> : null}
        </View>
      ) : null}

      {item.decided_at ? (
        <Text style={ui.muted}>
          Decided {formatWhen(item.decided_at)}
          {item.decided_via ? ` via ${item.decided_via}` : ""}
          {item.decision_note ? `: ${item.decision_note}` : ""}
        </Text>
      ) : null}

      {item.can_decide && postsSomething && publishingOpen === false ? (
        <Text style={ui.muted}>
          Approving this schedules real posts, and publishing is not open yet. You can reject it now, or leave
          it here and approve it once publishing opens.
        </Text>
      ) : null}

      {error ? <Text style={ui.error} accessibilityRole="alert">{error}</Text> : null}

      {item.can_decide ? (
        <View style={ui.row}>
          <ActionButton
            label={editing ? "Approve with edits" : "Approve"}
            icon="checkmark"
            onPress={() => void decide("approve")}
            busy={busy === "approve"}
            disabled={busy !== "" || blocked}
          />
          {editable && !editing ? (
            <ActionButton label="Edit" variant="ghost" onPress={() => setEditing(true)} disabled={busy !== ""} />
          ) : null}
          {!showNote ? (
            <ActionButton label="Comment" variant="ghost" onPress={() => setShowNote(true)} disabled={busy !== ""} />
          ) : null}
          <ActionButton
            label="Reject"
            variant="ghost"
            icon="close"
            onPress={() => void decide("reject")}
            busy={busy === "reject"}
            disabled={busy !== ""}
          />
        </View>
      ) : null}
    </View>
  );
}
