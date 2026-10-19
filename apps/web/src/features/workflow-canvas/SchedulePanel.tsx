"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import type { WorkflowSchedule } from "./api";
import { WEEKDAYS } from "./graph";

export function SchedulePanel({
  schedule,
  busy,
  onSave,
}: {
  schedule: WorkflowSchedule;
  busy: boolean;
  onSave: (value: { enabled: boolean; weekday: number | null; hour: number }) => void;
}) {
  const [enabled, setEnabled] = React.useState(schedule.enabled);
  const [weekday, setWeekday] = React.useState<number | null>(schedule.enabled ? schedule.weekday : 0);
  const [hour, setHour] = React.useState(schedule.hour);
  React.useEffect(() => {
    setEnabled(schedule.enabled);
    setWeekday(schedule.enabled ? schedule.weekday : 0);
    setHour(schedule.hour);
  }, [schedule]);
  return (
    <div className="space-y-2" data-testid="schedule-panel">
      <h3 className="text-sm font-semibold">Schedule</h3>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        Run on a schedule
      </label>
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label htmlFor="wf-day">Day</Label>
          <select
            id="wf-day"
            className="neu-inset h-9 w-full rounded-md bg-transparent px-2 text-sm"
            value={weekday === null ? "daily" : String(weekday)}
            disabled={!enabled}
            onChange={(e) => setWeekday(e.target.value === "daily" ? null : Number(e.target.value))}
          >
            <option value="daily">Every day</option>
            {WEEKDAYS.map((d, i) => (
              <option key={d} value={i}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="wf-hour">Hour (UTC)</Label>
          <select
            id="wf-hour"
            className="neu-inset h-9 w-full rounded-md bg-transparent px-2 text-sm"
            value={hour}
            disabled={!enabled}
            onChange={(e) => setHour(Number(e.target.value))}
          >
            {Array.from({ length: 24 }, (_, h) => (
              <option key={h} value={h}>
                {String(h).padStart(2, "0")}:00
              </option>
            ))}
          </select>
        </div>
      </div>
      {schedule.enabled ? (
        <p className="text-xs text-muted-foreground">
          {schedule.label}
          {schedule.next_run_at ? `. Next: ${schedule.next_run_at.slice(0, 16).replace("T", " ")} UTC` : ""}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">Scheduled runs only queue approvals; nothing is spent on its own.</p>
      )}
      <Button size="sm" variant="secondary" disabled={busy} onClick={() => onSave({ enabled, weekday, hour })}>
        Save schedule
      </Button>
    </div>
  );
}
