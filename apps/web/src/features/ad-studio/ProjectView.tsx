"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ExternalLink, Loader2, Save, Trash2, Users, WandSparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { POLL_INTERVAL_MS } from "@/src/shared/api";
import { AnglesEditor } from "./AnglesEditor";
import {
  createVariants,
  deleteAdProject,
  deleteVariant,
  getAdProject,
  isActive,
  regenerateAngles,
  retryVariant,
  startAvatarReel,
  updateAdProject,
  type AdAngle,
  type AdVariant,
  type ProjectDetail,
  type VariantsInput,
} from "./api";
import { BatchBuilder } from "./BatchBuilder";
import { ExportPanel } from "./ExportPanel";
import { ProductCard } from "./ProductCard";
import { PublishAndTest } from "./PublishAndTest";
import { rallyOnboardUrl } from "./rally-link";
import { ErrorText, LoadError, errorMessage, useRequestOptions } from "./shared";
import { VariantGrid, type VariantActions } from "./VariantGrid";

/** Idempotency key per ad and attempt, persisted so a reload never double-charges. */
function avatarKey(ad: AdVariant): string {
  const storageKey = `adstudio:reel-key:${ad.id}`;
  try {
    const existing = window.sessionStorage.getItem(storageKey);
    if (existing) return existing;
    const fresh = `adstudio-${ad.id}-${Date.now().toString(36)}`;
    window.sessionStorage.setItem(storageKey, fresh);
    return fresh;
  } catch {
    return `adstudio-${ad.id}`;
  }
}

function forgetAvatarKey(ad: AdVariant): void {
  try {
    window.sessionStorage.removeItem(`adstudio:reel-key:${ad.id}`);
  } catch {
    // storage unavailable: nothing to forget
  }
}

export function ProjectView({
  projectId,
  rallyWebUrl = null,
}: {
  projectId: string;
  /** Rally origin (RALLY_WEB_URL) for the "Find buyers" deep link; hidden when null. */
  rallyWebUrl?: string | null;
}) {
  const router = useRouter();
  const requestOptions = useRequestOptions();
  const [project, setProject] = React.useState<ProjectDetail | null>(null);
  const [angles, setAngles] = React.useState<AdAngle[]>([]);
  const [anglesDirty, setAnglesDirty] = React.useState(false);
  const [title, setTitle] = React.useState("");
  const [busy, setBusy] = React.useState<"" | "angles" | "regen" | "title" | "delete">("");
  const [error, setError] = React.useState("");
  const [loadFailure, setLoadFailure] = React.useState<unknown>(null);

  const load = React.useCallback(async () => {
    try {
      const data = await getAdProject(projectId, await requestOptions());
      setProject(data);
      setTitle((t) => t || data.title);
      setAngles((current) => (current.length === 0 ? data.angles : current));
      setLoadFailure(null);
    } catch (err) {
      setLoadFailure(err);
    }
  }, [projectId, requestOptions]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const polling = project?.variants.some((v) => isActive(v.status)) ?? false;
  React.useEffect(() => {
    if (!polling) return;
    const timer = window.setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [polling, load]);

  const guarded = async (kind: typeof busy, fn: () => Promise<void>) => {
    setBusy(kind);
    setError("");
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  };

  const saveAngles = () =>
    guarded("angles", async () => {
      await updateAdProject(projectId, { angles }, await requestOptions());
      setAnglesDirty(false);
      setAngles([]);
      await load();
    });

  const regenerate = () =>
    guarded("regen", async () => {
      const data = await regenerateAngles(projectId, { use_llm: true }, await requestOptions());
      setAngles(data.angles);
      setAnglesDirty(false);
      await load();
    });

  const rename = () =>
    guarded("title", async () => {
      await updateAdProject(projectId, { title }, await requestOptions());
      await load();
    });

  const remove = () =>
    guarded("delete", async () => {
      if (!window.confirm("Delete this ad project? Rendered videos stay in your uploads library.")) return;
      await deleteAdProject(projectId, await requestOptions());
      router.push("/ad-studio");
    });

  const submitBatch = async (input: VariantsInput) => {
    if (anglesDirty) throw new Error("Save your angle edits before rendering.");
    await createVariants(projectId, input, await requestOptions());
    await load();
  };

  const actions: VariantActions = {
    onRetry: async (ad) => {
      forgetAvatarKey(ad);
      await retryVariant(projectId, ad.id, await requestOptions()).catch((err) => setError(errorMessage(err)));
      await load();
    },
    onDelete: async (ad) => {
      await deleteVariant(projectId, ad.id, await requestOptions()).catch((err) => setError(errorMessage(err)));
      await load();
    },
    onStartAvatar: async (ad) => {
      await startAvatarReel(projectId, ad, avatarKey(ad), await requestOptions()).catch((err) =>
        setError(errorMessage(err)),
      );
      await load();
    },
  };

  if (!project) {
    return loadFailure ? (
      <LoadError
        error={loadFailure}
        onRetry={() => void load()}
        fallback="We couldn't open this ad project. Please try again."
      />
    ) : (
      <div className="space-y-4">
        <Skeleton className="h-10 w-1/2" />
        <Skeleton className="h-56" />
      </div>
    );
  }

  const readyCount = project.variants.filter((v) => v.status === "done").length;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href="/ad-studio" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" aria-hidden /> All ad projects
        </Link>
        <Button variant="ghost" size="sm" onClick={remove} disabled={busy !== ""}>
          <Trash2 aria-hidden /> Delete project
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Input aria-label="Project title" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} className="max-w-xl text-lg font-semibold" />
        <Button variant="outline" size="sm" onClick={rename} disabled={busy !== "" || !title.trim() || title === project.title}>
          <Save aria-hidden /> Rename
        </Button>
      </div>
      <ErrorText message={error} />
      {loadFailure ? <LoadError error={loadFailure} onRetry={() => void load()} fallback="We couldn't refresh this project. Please try again." /> : null}

      <ProductCard product={project.product} images={project.images.map((i) => i.url).filter((u): u is string => Boolean(u))} />

      <section className="space-y-3" aria-labelledby="angles-h">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="angles-h" className="text-lg font-semibold">Ad angles</h2>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={regenerate} disabled={busy !== ""}>
              {busy === "regen" ? <Loader2 className="animate-spin" aria-hidden /> : <WandSparkles aria-hidden />} Rewrite with AI
            </Button>
            <Button size="sm" onClick={saveAngles} disabled={busy !== "" || !anglesDirty}>
              <Save aria-hidden /> Save angles
            </Button>
          </div>
        </div>
        <AnglesEditor
          angles={angles}
          onChange={(next) => {
            setAngles(next);
            setAnglesDirty(true);
          }}
          disabled={busy !== ""}
        />
        <p className="text-xs text-muted-foreground">
          Rewriting replaces the saved angles. Ads already rendered keep the copy they were made with.
        </p>
      </section>

      <section className="space-y-3" aria-labelledby="batch-h">
        <h2 id="batch-h" className="text-lg font-semibold">Render ads</h2>
        <BatchBuilder angles={project.angles} hasImages={project.images.length > 0} onSubmit={submitBatch} />
      </section>

      <section className="space-y-3" aria-labelledby="ads-h">
        <h2 id="ads-h" className="text-lg font-semibold">Ads</h2>
        <ExportPanel projectId={projectId} readyCount={readyCount} />
        <VariantGrid
          variants={project.variants}
          actions={actions}
          sourceUrl={project.source_url || project.product.url}
        />
      </section>

      <section className="space-y-3" aria-labelledby="test-h">
        <h2 id="test-h" className="text-lg font-semibold">Publish and test</h2>
        <PublishAndTest projectId={projectId} variants={project.variants} onVariantsChanged={load} />
      </section>

      {rallyWebUrl ? (
        <FindBuyers rallyWebUrl={rallyWebUrl} productUrl={project.source_url || project.product.url} />
      ) : null}
    </div>
  );
}

/** Menivor -> Rally bridge: take the product to Rally to find people who would buy it. */
function FindBuyers({ rallyWebUrl, productUrl }: { rallyWebUrl: string; productUrl: string | null }) {
  return (
    <section
      className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-4"
      aria-labelledby="find-buyers-h"
    >
      <div className="max-w-2xl">
        <h2 id="find-buyers-h" className="font-semibold">Find buyers for this product</h2>
        <p className="text-sm text-muted-foreground">
          Rally reads {productUrl ? "this product's site" : "your site"}, suggests who is likely to buy it
          and drafts outreach for you to review. Pay as you go.
        </p>
      </div>
      <Button asChild variant="outline">
        <a href={rallyOnboardUrl(rallyWebUrl, productUrl)} target="_blank" rel="noopener noreferrer">
          <Users aria-hidden /> Find buyers in Rally <ExternalLink aria-hidden />
        </a>
      </Button>
    </section>
  );
}
