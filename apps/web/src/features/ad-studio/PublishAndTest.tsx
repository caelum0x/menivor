"use client";

import * as React from "react";
import { Skeleton } from "@/components/ui/skeleton";
import type { AdVariant } from "./api";
import { PublishTestPanel } from "./PublishTestPanel";
import { checkTest, getTests, logResult, remakeWinner, startTest, stopTest, type TestsPayload } from "./publish-api";
import { LoadError, useRequestOptions } from "./shared";
import { TestResults, type TestActions } from "./TestResults";

const REFRESH_MS = 60_000;
const SETTLED = new Set(["winner_ready", "remade", "inconclusive", "cap_reached"]);

/** Project-page section: start a test and follow every test through to its winner. */
export function PublishAndTest({
  projectId,
  variants,
  onVariantsChanged,
}: {
  projectId: string;
  variants: AdVariant[];
  /** Reload the project (new remake renders appear in the Ads grid). */
  onVariantsChanged: () => Promise<void>;
}) {
  const requestOptions = useRequestOptions();
  const [payload, setPayload] = React.useState<TestsPayload | null>(null);
  const [error, setError] = React.useState<unknown>(null);

  const load = React.useCallback(async () => {
    try {
      setPayload(await getTests(projectId, await requestOptions()));
      setError(null);
    } catch (err) {
      setError(err);
    }
  }, [projectId, requestOptions]);

  // Re-read when ads finish rendering or join a test (the eligible set changes).
  const variantsKey = variants.map((v) => `${v.id}:${v.status}:${v.test_batch_id ?? ""}`).join("|");
  React.useEffect(() => {
    void load();
  }, [load, variantsKey]);

  const live = payload?.tests.some((t) => !t.stopped && !SETTLED.has(t.status)) ?? false;
  React.useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [live, load]);

  const actions: TestActions = {
    onCheck: async (test) => setPayload(await checkTest(projectId, test.batch_id, await requestOptions())),
    onStop: async (test) => {
      if (!window.confirm("Stop this test? Posts that have not gone out yet are canceled; live posts stay up.")) return;
      setPayload(await stopTest(projectId, test.batch_id, await requestOptions()));
    },
    onRemake: async (test, acceptLowConfidence) => {
      await remakeWinner(projectId, test.batch_id, acceptLowConfidence, await requestOptions());
      await onVariantsChanged();
      await load();
    },
    onLog: async (ad, input) => {
      await logResult(ad.job_id, input, await requestOptions());
      await load();
    },
  };

  if (!payload) {
    return error ? (
      <LoadError error={error} onRetry={() => void load()} fallback="We couldn't load your tests. Please try again." />
    ) : (
      <Skeleton className="h-32" />
    );
  }

  return (
    <div className="space-y-4">
      <PublishTestPanel
        payload={payload}
        variants={variants}
        onStart={async (input) => {
          const result = await startTest(projectId, input, await requestOptions());
          setPayload(result);
          await onVariantsChanged();
          return result.loop_note;
        }}
      />
      {error ? (
        <LoadError error={error} onRetry={() => void load()} fallback="We couldn't refresh your tests. Please try again." />
      ) : null}
      <TestResults tests={payload.tests} actions={actions} />
    </div>
  );
}
