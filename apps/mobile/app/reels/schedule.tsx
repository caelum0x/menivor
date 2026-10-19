/** Route: /reels/schedule — legacy alias for the canonical /scheduled manager. */
import { Redirect } from "expo-router";

export default function ReelScheduleRedirect() {
  return <Redirect href="/scheduled" />;
}
