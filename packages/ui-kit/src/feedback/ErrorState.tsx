import * as React from "react";
import { colors } from "../tokens/index.js";
export function ErrorState({ message, correlationId }: { message: string; correlationId?: string }) {
  return (
    <div style={{ padding: 16, border: `1px solid ${colors.error}`, borderRadius: 12, color: colors.error }}>
      <div style={{ fontSize: 14 }}>{message}</div>
      {correlationId ? <div style={{ color: colors.muted, fontSize: 11, marginTop: 4 }}>ref {correlationId}</div> : null}
    </div>
  );
}
