import { useCallback, useEffect, useState } from "react";

import { listJobs } from "../lib/api";
import type { Job } from "../lib/types";
import { JobState } from "../lib/types";

/** Human label + badge modifier for a job state. */
function stateMeta(state: number): { label: string; cls: string } {
  switch (state) {
    case JobState.Complete:
      return { label: "Complete", cls: "badge--ok" };
    case JobState.Failed:
      return { label: "Failed", cls: "badge--fail" };
    case JobState.Processing:
      return { label: "Processing", cls: "badge--run" };
    default:
      return { label: `State ${state}`, cls: "badge--run" };
  }
}

/** Library view: the caller's generated reels, newest-first as returned by the API. */
export function LibraryView() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setJobs(await listJobs());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load your reels.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="view">
      <div className="view-head view-head--row">
        <div>
          <h1 className="view-title">Your reels</h1>
          <p className="view-sub">Every reel you have generated from this account.</p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={() => void load()} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      {!loading && jobs.length === 0 && !error && (
        <div className="card panel empty">
          <p className="muted">No reels yet. Record a screen capture to get started.</p>
        </div>
      )}

      <div className="reel-grid">
        {jobs.map((job) => {
          const meta = stateMeta(job.state);
          return (
            <article key={job.job_id} className="card reel-card">
              <div className="reel-thumb">
                {job.result_url ? (
                  <video className="reel-video" src={job.result_url} controls preload="metadata" />
                ) : (
                  <div className="reel-placeholder">
                    <span className="muted">{meta.label}</span>
                  </div>
                )}
              </div>
              <div className="reel-meta">
                <span className={`badge ${meta.cls}`}>{meta.label}</span>
                <span className="reel-id" title={job.job_id}>
                  {job.job_id}
                </span>
              </div>
              {job.state === JobState.Failed && job.error && (
                <p className="error-text small">{job.error}</p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
