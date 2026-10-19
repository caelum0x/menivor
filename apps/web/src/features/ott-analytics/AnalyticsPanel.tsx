"use client";

import * as React from "react";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { addTeamMember, getDashboard, getTeam, removeTeamMember, type Dashboard, type TeamMember } from "./api";

/** Plays, watch time and playback quality from our own player beacons, plus who else can see them. */
export function AnalyticsPanel() {
  const getApiToken = useApiToken();
  const [days, setDays] = React.useState(7);
  const [data, setData] = React.useState<Dashboard | null>(null);
  const [team, setTeam] = React.useState<readonly TeamMember[]>([]);
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState<TeamMember["role"]>("analyst");
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const token = await getApiToken();
        const [dash, members] = await Promise.all([getDashboard(days, { token }), getTeam({ token })]);
        if (!live) return;
        setData(dash);
        setTeam(members.members);
      } catch (err) {
        if (live) setError(friendlyErrorMessage(err, "Analytics could not load."));
      }
    })();
    return () => {
      live = false;
    };
  }, [days, getApiToken]);

  const add = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      setTeam((await addTeamMember(email, role, { token: await getApiToken() })).members);
      setEmail("");
    } catch (err) {
      setError(friendlyErrorMessage(err, "That person could not be added."));
    }
  };

  return (
    <section aria-label="Channel analytics" className="space-y-3 rounded-xl border border-border p-3 text-sm">
      <div className="flex items-center gap-3">
        <h2 className="font-semibold">Analytics</h2>
        <label>Last
          <select className="mx-1 rounded border px-1" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[1, 7, 30, 90].map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
          days
        </label>
      </div>
      {data ? (
        <>
          <p data-totals>
            {data.totals.plays} plays, {data.totals.viewers} viewers, {data.totals.watch_minutes} minutes watched,{" "}
            {data.totals.stalls} stalls, {data.totals.errors} errors
          </p>
          <table className="w-full text-left">
            <thead><tr><th>Title</th><th>Plays</th><th>Minutes</th><th>Start (p95)</th><th>Stalls</th></tr></thead>
            <tbody>
              {data.titles.map((t) => (
                <tr key={t.title_id}>
                  <td>{t.title}</td><td>{t.plays}</td><td>{t.watch_minutes}</td>
                  <td>{(t.startup_p95_ms / 1000).toFixed(1)} s</td><td>{t.stalls}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-muted-foreground">Counted from our own player only.</p>
        </>
      ) : null}
      <form onSubmit={add} className="flex flex-wrap items-end gap-2" aria-label="Add to my team">
        <label>Email<input className="ml-2 rounded border px-2 py-1" type="email" required value={email}
          onChange={(e) => setEmail(e.target.value)} /></label>
        <label>Role
          <select className="ml-2 rounded border px-1" value={role} onChange={(e) => setRole(e.target.value as TeamMember["role"])}>
            <option value="analyst">Sees analytics</option>
            <option value="editor">Edits titles</option>
          </select>
        </label>
        <button type="submit" className="rounded-lg border px-3 py-1">Add</button>
      </form>
      <ul>
        {team.map((m) => (
          <li key={m.id}>{m.email} ({m.role}){" "}
            <button type="button" className="underline" onClick={async () => {
              setTeam((await removeTeamMember(m.id, { token: await getApiToken() })).members);
            }}>Remove</button>
          </li>
        ))}
      </ul>
      {error ? <p role="alert">{error}</p> : null}
    </section>
  );
}
