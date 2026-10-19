"use client";

import * as React from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { presignAndUpload } from "@/lib/api";
import { signInHref } from "@/lib/auth-redirect";
import { useSignedInState } from "@/lib/auth-state";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import {
  addOriginal,
  listBrands,
  listMyCharacters,
  listNarrators,
  setProductShots,
  startTraining,
  trainingQuote,
  type BrandKit,
  type MyCharacter,
  type Narrator,
  type TrainingQuote,
} from "./api";
import { RealFaceForm } from "./RealFaceForm";

/** Create once, reuse in every preset: original characters, yourself, and brand kits. */
export function MyCharacters() {
  const { isLoaded, isSignedIn } = useSignedInState();
  const getApiToken = useApiToken();
  const [characters, setCharacters] = React.useState<readonly MyCharacter[] | null>(null);
  const [narrators, setNarrators] = React.useState<{ available: boolean; narrators: readonly Narrator[] } | null>(null);
  const [brands, setBrands] = React.useState<readonly BrandKit[]>([]);
  const [quotes, setQuotes] = React.useState<Record<string, TrainingQuote>>({});
  const [training, setTraining] = React.useState<Record<string, string>>({});
  const [showSelf, setShowSelf] = React.useState(false);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const token = await getApiToken();
      const [mine, roster, kits] = await Promise.all([
        listMyCharacters({ token }),
        listNarrators({ token }).catch(() => ({ available: false, narrators: [] })),
        listBrands({ token }),
      ]);
      setCharacters(mine);
      setNarrators(roster);
      setBrands(kits);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Your characters could not load."));
    }
  }, [getApiToken]);

  React.useEffect(() => {
    if (isSignedIn) void load();
  }, [isSignedIn, load]);

  async function run(action: () => Promise<void>, fallback: string) {
    setError("");
    try {
      await action();
    } catch (err) {
      setError(friendlyErrorMessage(err, fallback));
    }
  }

  if (isLoaded && !isSignedIn) {
    return (
      <Button asChild>
        <Link href={signInHref("/presets-gallery?characters=1")}>Sign in to manage your characters</Link>
      </Button>
    );
  }
  return (
    <div className="space-y-10">
      <section aria-labelledby="mine-title" className="space-y-3">
        <h2 id="mine-title" className="text-xl font-semibold">Your characters</h2>
        {characters === null ? <p className="text-sm text-muted-foreground">Loading</p> : null}
        {characters?.length === 0 ? <p className="text-sm text-muted-foreground">No characters yet.</p> : null}
        <ul className="space-y-2">
          {characters?.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-border p-3">
              <span className="font-medium">{c.name}</span>
              <span className="text-xs text-muted-foreground">
                {c.kind === "original" ? "Original character" : c.kind === "real_face" ? "You, with consent" : "Described"}
              </span>
              {c.kind === "real_face" && !c.trained ? (
                quotes[c.id] ? (
                  training[c.id] ? (
                    <span className="text-sm">Training started</span>
                  ) : (
                    <Button
                      size="sm"
                      onClick={() =>
                        run(async () => {
                          const token = await getApiToken();
                          const job = await startTraining(c.id, quotes[c.id]!.credits, { token });
                          setTraining((prev) => ({ ...prev, [c.id]: job.job_id }));
                        }, "Training could not start.")
                      }
                    >
                      Train for {quotes[c.id]!.credits} AI-video credits
                    </Button>
                  )
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      run(async () => {
                        const token = await getApiToken();
                        const quote = await trainingQuote(c.id, { token });
                        setQuotes((prev) => ({ ...prev, [c.id]: quote }));
                      }, "We could not price training.")
                    }
                  >
                    See the training price
                  </Button>
                )
              ) : null}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="originals-title" className="space-y-3">
        <h2 id="originals-title" className="text-xl font-semibold">Original characters</h2>
        {narrators && !narrators.available ? (
          <p className="text-sm text-muted-foreground">Original characters arrive after their art review.</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {narrators?.narrators.map((n) => (
              <li key={n.id}>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    run(async () => {
                      const token = await getApiToken();
                      await addOriginal(n.id, { token });
                      await load();
                    }, "This character could not be added.")
                  }
                >
                  Add {n.name}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="self-title" className="space-y-3">
        <h2 id="self-title" className="text-xl font-semibold">A character of yourself</h2>
        {showSelf ? (
          <RealFaceForm
            onCreated={() => {
              setShowSelf(false);
              void load();
            }}
          />
        ) : (
          <Button variant="outline" onClick={() => setShowSelf(true)}>Start</Button>
        )}
      </section>

      <section aria-labelledby="brands-title" className="space-y-3">
        <h2 id="brands-title" className="text-xl font-semibold">Brand kits</h2>
        {brands.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No brand kits yet. <Link className="underline underline-offset-4" href="/presets">Make one</Link>.
          </p>
        ) : (
          <ul className="space-y-2">
            {brands.map((kit) => (
              <li key={kit.id} className="space-y-2 rounded-xl border border-border p-3">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{kit.name}</span>
                  {kit.colors.map((color) => (
                    <span key={color} className="inline-block size-4 rounded-full border" style={{ background: color }} />
                  ))}
                </div>
                <label className="block text-sm">
                  <span>Product shots ({kit.product_shots.length})</span>
                  <input
                    type="file"
                    accept="image/*"
                    multiple
                    aria-label={`Product shots for ${kit.name}`}
                    className="mt-1 block text-sm"
                    onChange={(e) => {
                      const files = Array.from(e.target.files ?? []);
                      void run(async () => {
                        const token = await getApiToken();
                        const keys = [...kit.product_shots];
                        for (const file of files) keys.push((await presignAndUpload(file, { token })).key);
                        await setProductShots(kit.id, keys, { token });
                        await load();
                      }, "The product shots could not be saved.");
                    }}
                  />
                </label>
              </li>
            ))}
          </ul>
        )}
      </section>
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </div>
  );
}
