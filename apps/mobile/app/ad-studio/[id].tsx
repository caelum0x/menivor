/** Route: /ad-studio/[id] — one Ad Studio project (angles, batch, ads). */
import { Redirect, Stack, useLocalSearchParams } from "expo-router";

import { ProjectScreen } from "@/src/features/ad-studio";

/** Project ids are short server ids; anything else never reaches the API. */
const PROJECT_ID_PATTERN = /^[A-Za-z0-9_-]{1,32}$/;

export default function AdStudioProjectRoute() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const projectId = typeof id === "string" ? id.trim() : "";
  if (!PROJECT_ID_PATTERN.test(projectId)) return <Redirect href={"/ad-studio" as never} />;
  return (
    <>
      <Stack.Screen options={{ title: "Ad project", presentation: "card" }} />
      <ProjectScreen projectId={projectId} />
    </>
  );
}
