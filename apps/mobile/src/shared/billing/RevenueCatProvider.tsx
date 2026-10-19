import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from "react";

import type { CustomerInfo } from "react-native-purchases";

import { me } from "@/lib/api";
import { useSession } from "@/src/shared/auth";
import {
  canExportWithEntitlement,
  entitlementSnapshotFromCustomerInfo,
  initialEntitlementSnapshot,
  PRO_ENTITLEMENT_ID,
  type EntitlementSnapshot,
} from "./entitlement-policy";
import {
  configureRevenueCat,
  forgetRevenueCatUser,
  getRevenueCatCustomerInfo,
  identifyRevenueCatUser,
  listenForRevenueCatCustomerInfo,
  presentRevenueCatCustomerCenter,
  restoreRevenueCatPurchases,
  revenueCatPublicConfig,
  type RevenueCatPublicConfig,
} from "./revenuecat-adapter";
import { MenivorProSheet } from "./MenivorProSheet";

interface ExportAccessResult {
  allowed: boolean;
  snapshot: EntitlementSnapshot;
}

interface RevenueCatContextValue {
  snapshot: EntitlementSnapshot;
  refresh: () => Promise<EntitlementSnapshot>;
  restore: () => Promise<EntitlementSnapshot>;
  presentPaywall: () => Promise<EntitlementSnapshot>;
  presentCustomerCenter: () => Promise<EntitlementSnapshot>;
  requireProAccess: () => Promise<ExportAccessResult>;
  requireProExport: () => Promise<ExportAccessResult>;
}

const RevenueCatContext = createContext<RevenueCatContextValue | null>(null);

function errorSnapshot(
  config: RevenueCatPublicConfig | null,
  appUserId: string | null,
  error: unknown,
): EntitlementSnapshot {
  return {
    status: "error",
    entitlementId: config?.entitlementId ?? PRO_ENTITLEMENT_ID,
    appUserId,
    checkedAtMs: null,
    expiresAtMs: null,
    verification: "unknown",
    message:
      error instanceof Error && error.message.trim()
        ? error.message
        : "Unable to verify Pro access.",
  };
}

export function RevenueCatProvider({ children }: PropsWithChildren) {
  const { apiKey, loading: sessionLoading } = useSession();
  const config = useMemo(() => revenueCatPublicConfig(), []);
  const [snapshot, setSnapshot] = useState<EntitlementSnapshot>(() =>
    config
      ? initialEntitlementSnapshot("loading", config.entitlementId)
      : initialEntitlementSnapshot("unconfigured"),
  );
  const snapshotRef = useRef(snapshot);
  const appUserIdRef = useRef<string | null>(null);
  const [proSheetVisible, setProSheetVisible] = useState(false);
  const proSheetDoneRef = useRef<(() => void) | null>(null);
  const closeProSheet = useCallback(() => {
    setProSheetVisible(false);
    const done = proSheetDoneRef.current;
    proSheetDoneRef.current = null;
    done?.();
  }, []);
  const readyRef = useRef(false);

  const publish = useCallback((next: EntitlementSnapshot) => {
    snapshotRef.current = next;
    setSnapshot(next);
    return next;
  }, []);

  const publishCustomerInfo = useCallback(
    (customerInfo: CustomerInfo) => {
      const userId = appUserIdRef.current;
      if (!config || !userId) return snapshotRef.current;
      return publish(
        entitlementSnapshotFromCustomerInfo(
          customerInfo,
          config.entitlementId,
          userId,
        ),
      );
    },
    [config, publish],
  );

  useEffect(() => {
    let active = true;
    let stopListening: (() => void) | undefined;

    if (sessionLoading) return undefined;

    if (!config) {
      readyRef.current = false;
      appUserIdRef.current = null;
      publish(
        initialEntitlementSnapshot(
          "unconfigured",
          PRO_ENTITLEMENT_ID,
          "RevenueCat public keys are missing for this platform.",
        ),
      );
      return undefined;
    }

    if (!apiKey) {
      readyRef.current = false;
      appUserIdRef.current = null;
      publish(initialEntitlementSnapshot("signed_out", config.entitlementId));
      void forgetRevenueCatUser().catch(() => undefined);
      return undefined;
    }

    publish(initialEntitlementSnapshot("loading", config.entitlementId));

    const start = async () => {
      try {
        const profile = await me({ token: apiKey });
        if (!profile.user_id.trim()) {
          throw new Error("The backend returned no user identity for billing.");
        }

        configureRevenueCat(config, profile.user_id);
        const customerInfo = await identifyRevenueCatUser(profile.user_id);
        if (!active) return;

        appUserIdRef.current = profile.user_id;
        readyRef.current = true;
        publishCustomerInfo(customerInfo);
        stopListening = listenForRevenueCatCustomerInfo((next) => {
          if (active) publishCustomerInfo(next);
        });
      } catch (error) {
        if (!active) return;
        readyRef.current = false;
        publish(errorSnapshot(config, appUserIdRef.current, error));
      }
    };

    void start();
    return () => {
      active = false;
      stopListening?.();
    };
  }, [apiKey, config, publish, publishCustomerInfo, sessionLoading]);

  const refresh = useCallback(async () => {
    if (!config || !readyRef.current || !appUserIdRef.current) {
      return snapshotRef.current;
    }
    try {
      return publishCustomerInfo(await getRevenueCatCustomerInfo());
    } catch (error) {
      return publish(errorSnapshot(config, appUserIdRef.current, error));
    }
  }, [config, publish, publishCustomerInfo]);

  const restore = useCallback(async () => {
    if (!config || !readyRef.current || !appUserIdRef.current) {
      return snapshotRef.current;
    }
    try {
      return publishCustomerInfo(await restoreRevenueCatPurchases());
    } catch (error) {
      return publish(errorSnapshot(config, appUserIdRef.current, error));
    }
  }, [config, publish, publishCustomerInfo]);

  const presentPaywall = useCallback(async () => {
    if (!config || !readyRef.current || !appUserIdRef.current) {
      return snapshotRef.current;
    }
    try {
      // Menivor's own Pro sheet (store-priced packages); resolves on close.
      await new Promise<void>((resolve) => {
        proSheetDoneRef.current?.();
        proSheetDoneRef.current = resolve;
        setProSheetVisible(true);
      });
      return publishCustomerInfo(await getRevenueCatCustomerInfo());
    } catch (error) {
      return publish(errorSnapshot(config, appUserIdRef.current, error));
    }
  }, [config, publish, publishCustomerInfo]);

  const presentCustomerCenter = useCallback(async () => {
    if (!config || !readyRef.current || !appUserIdRef.current) {
      return snapshotRef.current;
    }
    try {
      await presentRevenueCatCustomerCenter();
      return publishCustomerInfo(await getRevenueCatCustomerInfo());
    } catch (error) {
      return publish(errorSnapshot(config, appUserIdRef.current, error));
    }
  }, [config, publish, publishCustomerInfo]);

  const requireProAccess = useCallback(async (): Promise<ExportAccessResult> => {
    const fresh = await refresh();
    if (canExportWithEntitlement(fresh)) {
      return { allowed: true, snapshot: fresh };
    }

    if (fresh.status === "inactive") {
      const afterPaywall = await presentPaywall();
      return {
        allowed: canExportWithEntitlement(afterPaywall),
        snapshot: afterPaywall,
      };
    }

    return { allowed: false, snapshot: fresh };
  }, [presentPaywall, refresh]);

  // Compatibility name for existing export surfaces. Publishing and sharing
  // use the broader access name while following the exact same Pro policy.
  const requireProExport = requireProAccess;

  const value = useMemo<RevenueCatContextValue>(
    () => ({
      snapshot,
      refresh,
      restore,
      presentPaywall,
      presentCustomerCenter,
      requireProAccess,
      requireProExport,
    }),
    [
      presentCustomerCenter,
      presentPaywall,
      refresh,
      requireProAccess,
      requireProExport,
      restore,
      snapshot,
    ],
  );

  return (
    <RevenueCatContext.Provider value={value}>
      {children}
      <MenivorProSheet
        visible={proSheetVisible}
        onClose={closeProSheet}
        onPurchased={closeProSheet}
        onRestore={restore}
      />
    </RevenueCatContext.Provider>
  );
}

export function useRevenueCat(): RevenueCatContextValue {
  const value = useContext(RevenueCatContext);
  if (!value) {
    throw new Error("useRevenueCat must be used within RevenueCatProvider");
  }
  return value;
}
