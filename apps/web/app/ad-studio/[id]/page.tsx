import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { ProjectView } from "@/src/features/ad-studio/ProjectView";
import { rallyWebUrl } from "@/src/features/ad-studio/rally-link";

/** One Ad Studio project: product, angles, batch rendering and export. */
export default async function AdStudioProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // Read at request time on the server so RALLY_WEB_URL can change without a rebuild.
  const rallyUrl = rallyWebUrl(process.env.RALLY_WEB_URL ?? process.env.NEXT_PUBLIC_RALLY_WEB_URL);
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-6xl py-8">
        {id ? <ProjectView projectId={id} rallyWebUrl={rallyUrl} /> : null}
      </section>
    </main>
  );
}
