import { useEffect, useState } from "react";
import { AppState, type AppStateStatus } from "react-native";

/** Reactive native application state used to suspend network polling. */
export function useAppStateStatus(): AppStateStatus {
  const [status, setStatus] = useState<AppStateStatus>(AppState.currentState);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", setStatus);
    return () => subscription.remove();
  }, []);

  return status;
}
