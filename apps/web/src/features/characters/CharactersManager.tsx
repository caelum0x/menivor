"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Film, Loader2, Trash2, UserPlus, Users } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  characterShotPrompt,
  createCharacter,
  deleteCharacter,
  getCharacter,
  listCharacters,
  type Character,
  type ShotPrompt,
} from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

function errText(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

/**
 * Character studio: save reusable identity-locked characters (dedupes by
 * identity), delete them, inspect a rebuildable profile, and generate a locked
 * shot prompt — all wired to the real /characters domain.
 */
export function CharactersManager() {
  const { getToken } = useAuth();
  const [characters, setCharacters] = React.useState<Character[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [name, setName] = React.useState("");
  const [descriptors, setDescriptors] = React.useState("");
  const [style, setStyle] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [deletingId, setDeletingId] = React.useState("");
  const [selected, setSelected] = React.useState<Character | null>(null);

  const load = React.useCallback(async () => {
    try {
      const token = (await getToken()) ?? undefined;
      const res = await listCharacters({ token });
      setCharacters(res.characters);
    } catch (err) {
      setError(errText(err, "Failed to load."));
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const onCreate = React.useCallback(async () => {
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      await createCharacter(
        {
          name: name.trim(),
          descriptors: descriptors.split(",").map((s) => s.trim()).filter(Boolean),
          style: style.trim(),
        },
        { token },
      );
      setName("");
      setDescriptors("");
      setStyle("");
      await load();
    } catch (err) {
      setError(errText(err, "Failed to save."));
    } finally {
      setBusy(false);
    }
  }, [name, descriptors, style, getToken, load]);

  const onDelete = React.useCallback(
    async (id: string) => {
      setDeletingId(id);
      setError("");
      try {
        const token = (await getToken()) ?? undefined;
        await deleteCharacter(id, { token });
        setSelected((cur) => (cur?.id === id ? null : cur));
        await load();
      } catch (err) {
        setError(errText(err, "Failed to delete."));
      } finally {
        setDeletingId("");
      }
    },
    [getToken, load],
  );

  const onSelect = React.useCallback(
    async (id: string) => {
      setError("");
      try {
        const token = (await getToken()) ?? undefined;
        const full = await getCharacter(id, { token });
        setSelected(full);
      } catch (err) {
        setError(errText(err, "Failed to open character."));
      }
    },
    [getToken],
  );

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="space-y-3 py-5">
          <div className="flex items-center gap-2">
            <UserPlus className="h-4 w-4 text-primary" aria-hidden />
            <h2 className="font-semibold">New character</h2>
          </div>
          <Input placeholder="Name (e.g. Nova)" value={name} onChange={(e) => setName(e.target.value)} />
          <Input
            placeholder="Descriptors, comma-separated (silver hair, red jacket)"
            value={descriptors}
            onChange={(e) => setDescriptors(e.target.value)}
          />
          <Input placeholder="Style (e.g. 3D pixar)" value={style} onChange={(e) => setStyle(e.target.value)} />
          <Button onClick={() => void onCreate()} disabled={busy || !name.trim()}>
            {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden /> : null}
            Save character
          </Button>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>

      <div>
        <div className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
          <Users className="h-4 w-4" aria-hidden /> Your characters
        </div>
        {loading ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
          </p>
        ) : characters.length === 0 ? (
          <p className="text-sm text-muted-foreground">No characters yet — save one above.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {characters.map((c) => (
              <Card key={c.id}>
                <CardContent className="space-y-2 py-4">
                  <div className="flex items-start justify-between gap-2">
                    <button
                      type="button"
                      className="text-left font-medium hover:underline"
                      onClick={() => void onSelect(c.id)}
                    >
                      {c.name}
                    </button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Delete ${c.name}`}
                      disabled={deletingId === c.id}
                      onClick={() => void onDelete(c.id)}
                    >
                      {deletingId === c.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                      ) : (
                        <Trash2 className="h-4 w-4" aria-hidden />
                      )}
                    </Button>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {c.style && <Badge variant="secondary">{c.style}</Badge>}
                    {c.descriptors.map((d) => (
                      <Badge key={d} variant="outline">
                        {d}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {selected && (
        <CharacterShotPanel character={selected} getToken={getToken} onError={setError} />
      )}
    </div>
  );
}

interface CharacterShotPanelProps {
  character: Character;
  getToken: () => Promise<string | null>;
  onError: (msg: string) => void;
}

/** Detail + locked shot-prompt generator for one selected character. */
function CharacterShotPanel({ character, getToken, onError }: CharacterShotPanelProps) {
  const [action, setAction] = React.useState("");
  const [scene, setScene] = React.useState("");
  const [prompt, setPrompt] = React.useState<ShotPrompt | null>(null);
  const [busy, setBusy] = React.useState(false);

  const onGenerate = React.useCallback(async () => {
    if (!action.trim()) return;
    setBusy(true);
    try {
      const token = (await getToken()) ?? undefined;
      const res = await characterShotPrompt(
        character.id,
        { action: action.trim(), scene: scene.trim() },
        { token },
      );
      setPrompt(res);
    } catch (err) {
      onError(errText(err, "Failed to generate shot prompt."));
    } finally {
      setBusy(false);
    }
  }, [action, scene, character.id, getToken, onError]);

  return (
    <Card>
      <CardContent className="space-y-3 py-5">
        <div className="flex items-center gap-2">
          <Film className="h-4 w-4 text-primary" aria-hidden />
          <h2 className="font-semibold">Shot prompt · {character.name}</h2>
          {character.identity_key && (
            <Badge variant="outline">id {character.identity_key.slice(0, 8)}</Badge>
          )}
        </div>
        <Input
          placeholder="Action (e.g. sipping coffee at a window)"
          value={action}
          onChange={(e) => setAction(e.target.value)}
        />
        <Input placeholder="Scene (optional)" value={scene} onChange={(e) => setScene(e.target.value)} />
        <Button onClick={() => void onGenerate()} disabled={busy || !action.trim()}>
          {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden /> : null}
          Generate locked shot
        </Button>
        {prompt && (
          <div className="space-y-1 rounded-md border bg-muted/40 p-3 text-sm">
            <p>
              <span className="font-medium">Prompt:</span> {prompt.prompt}
            </p>
            <p className="text-muted-foreground">
              <span className="font-medium">Negative:</span> {prompt.negative_prompt}
            </p>
            <p className="text-muted-foreground">
              <span className="font-medium">Seed:</span> {prompt.seed}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
