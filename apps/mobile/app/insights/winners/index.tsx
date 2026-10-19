/** Route: /insights/winners — winners board, loops in progress, candidates. */
import { Stack } from "expo-router";

import { WinnersBoardScreen } from "@/src/features/winner-loop";

export default function WinnersRoute() {
  return (
    <>
      <Stack.Screen options={{ title: "Winners", presentation: "card" }} />
      <WinnersBoardScreen />
    </>
  );
}
