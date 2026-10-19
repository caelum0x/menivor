/**
 * Film / Series Studio — the saved-projects list → plan → shots → render →
 * export flow.
 *
 * Stage "list" shows the caller's saved films (`GET /film/projects`). "New
 * film" collects a beat sheet + lead character and creates a persisted,
 * identity-locked project (`POST /film/projects`). Opening a project loads it
 * (`GET /film/projects/{id}`), renders each shot through the project-scoped
 * render endpoints, and exports the stitched final video. Every call is
 * owner-scoped via the session token.
 */

import * as React from "react";

import { useSession } from "@/src/shared/auth";

import { FilmPlanForm } from "./components/FilmPlanForm";
import { ProjectList } from "./components/ProjectList";
import { ProjectShotList } from "./components/ProjectShotList";

type Stage =
  | { name: "list" }
  | { name: "plan" }
  | { name: "shots"; projectId: string };

export function FilmStudioScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [stage, setStage] = React.useState<Stage>({ name: "list" });

  if (stage.name === "shots") {
    return (
      <ProjectShotList
        token={token}
        projectId={stage.projectId}
        onBack={() => setStage({ name: "list" })}
      />
    );
  }

  if (stage.name === "plan") {
    return (
      <FilmPlanForm
        token={token}
        onCreated={(project) => setStage({ name: "shots", projectId: project.id })}
        onCancel={() => setStage({ name: "list" })}
      />
    );
  }

  return (
    <ProjectList
      token={token}
      onOpen={(projectId) => setStage({ name: "shots", projectId })}
      onNew={() => setStage({ name: "plan" })}
    />
  );
}
