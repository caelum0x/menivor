import { AutopostShell, QueueScreen } from "@/src/features/autopost";

export const metadata = { title: "Autopost" };

/** Autopost home: the publish queue across every connected account. */
export default function AutopostPage() {
  return (
    <AutopostShell
      title="Autopost"
      subtitle="Your videos, posted to your TikTok, Instagram and YouTube accounts at a steady pace."
    >
      <QueueScreen />
    </AutopostShell>
  );
}
