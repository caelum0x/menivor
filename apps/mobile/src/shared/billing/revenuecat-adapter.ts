import { Platform } from "react-native";

import Purchases, {
  PRODUCT_CATEGORY,
  type CustomerInfo,
  type CustomerInfoUpdateListener,
  type PurchasesStoreProduct,
} from "react-native-purchases";
import RevenueCatUI from "react-native-purchases-ui";

import { PRO_ENTITLEMENT_ID } from "./entitlement-policy";

export interface RevenueCatPublicConfig {
  apiKey: string;
  entitlementId: string;
  platform: "ios" | "android" | "web";
}

let configuredApiKey: string | null = null;

function clean(value: string | undefined): string {
  return value?.trim() ?? "";
}

export function revenueCatPublicConfig(): RevenueCatPublicConfig | null {
  const platform = Platform.OS;
  if (platform !== "ios" && platform !== "android" && platform !== "web") {
    return null;
  }

  const apiKey =
    platform === "ios"
      ? clean(process.env.EXPO_PUBLIC_REVENUECAT_IOS_API_KEY)
      : platform === "android"
        ? clean(process.env.EXPO_PUBLIC_REVENUECAT_ANDROID_API_KEY)
        : clean(process.env.EXPO_PUBLIC_REVENUECAT_WEB_API_KEY);

  if (!apiKey) return null;

  return {
    apiKey,
    platform,
    entitlementId:
      clean(process.env.EXPO_PUBLIC_REVENUECAT_PRO_ENTITLEMENT_ID) ||
      PRO_ENTITLEMENT_ID,
  };
}

export function configureRevenueCat(
  config: RevenueCatPublicConfig,
  appUserId: string,
): void {
  if (configuredApiKey === config.apiKey) return;
  if (configuredApiKey !== null) {
    throw new Error(
      "RevenueCat public API key changed during this app session. Restart the app.",
    );
  }

  Purchases.configure({
    apiKey: config.apiKey,
    appUserID: appUserId,
    entitlementVerificationMode:
      Purchases.ENTITLEMENT_VERIFICATION_MODE.INFORMATIONAL,
  });
  configuredApiKey = config.apiKey;
}

export async function identifyRevenueCatUser(
  appUserId: string,
): Promise<CustomerInfo> {
  const current = await Purchases.getAppUserID();
  if (current === appUserId) return Purchases.getCustomerInfo();
  const result = await Purchases.logIn(appUserId);
  return result.customerInfo;
}

export async function forgetRevenueCatUser(): Promise<void> {
  if (configuredApiKey === null) return;
  const current = await Purchases.getAppUserID();
  if (current.startsWith("$RCAnonymousID:")) return;
  await Purchases.logOut();
}

export function getRevenueCatCustomerInfo(): Promise<CustomerInfo> {
  return Purchases.getCustomerInfo();
}

export function restoreRevenueCatPurchases(): Promise<CustomerInfo> {
  return Purchases.restorePurchases();
}

export function listenForRevenueCatCustomerInfo(
  listener: CustomerInfoUpdateListener,
): () => void {
  Purchases.addCustomerInfoUpdateListener(listener);
  return () => {
    Purchases.removeCustomerInfoUpdateListener(listener);
  };
}

export async function presentRevenueCatCustomerCenter(): Promise<void> {
  await RevenueCatUI.presentCustomerCenter();
}

/** A consumable credit pack as priced by the App Store / Play Store. */
export interface StoreCreditProduct {
  productId: string;
  title: string;
  priceString: string;
  price: number;
  currencyCode: string;
}

/** A completed store purchase the backend must verify and redeem. */
export interface StoreCreditPurchase {
  productId: string;
  transactionId: string;
  purchasedAt: string;
}

/** Thrown when the buyer dismissed the store sheet; not an error to show. */
export class StorePurchaseCancelledError extends Error {
  constructor() {
    super("Purchase cancelled.");
    this.name = "StorePurchaseCancelledError";
  }
}

const storeProductCache = new Map<string, PurchasesStoreProduct>();

function toCreditProduct(product: PurchasesStoreProduct): StoreCreditProduct {
  return {
    productId: product.identifier,
    title: product.title,
    priceString: product.priceString,
    price: product.price,
    currencyCode: product.currencyCode,
  };
}

/**
 * Load consumable (non-subscription) store products for the given ids. Ids the
 * store does not know (not yet approved / not attached to the app) are simply
 * absent from the result.
 */
export async function getStoreCreditProducts(
  productIds: readonly string[],
): Promise<StoreCreditProduct[]> {
  if (configuredApiKey === null) {
    throw new Error("In-app purchases are not configured for this build.");
  }
  if (productIds.length === 0) return [];
  const products = await Purchases.getProducts(
    [...productIds],
    PRODUCT_CATEGORY.NON_SUBSCRIPTION,
  );
  for (const product of products) {
    storeProductCache.set(product.identifier, product);
  }
  return products.map(toCreditProduct);
}

/**
 * Buy one consumable credit pack through the store. Resolves with the store
 * transaction the backend verifies against RevenueCat before granting credits;
 * nothing is credited on the device.
 */
export async function purchaseStoreCreditProduct(
  productId: string,
): Promise<StoreCreditPurchase> {
  if (configuredApiKey === null) {
    throw new Error("In-app purchases are not configured for this build.");
  }
  const product = storeProductCache.get(productId);
  if (!product) {
    throw new Error("This credit pack is no longer available. Refresh and try again.");
  }
  try {
    const result = await Purchases.purchaseStoreProduct(product);
    const transactionId = result.transaction?.transactionIdentifier?.trim() ?? "";
    if (!transactionId) {
      throw new Error("The store did not return a transaction for this purchase.");
    }
    return {
      productId: result.productIdentifier || productId,
      transactionId,
      purchasedAt: result.transaction.purchaseDate || new Date().toISOString(),
    };
  } catch (error) {
    if (
      error &&
      typeof error === "object" &&
      (error as { userCancelled?: unknown }).userCancelled === true
    ) {
      throw new StorePurchaseCancelledError();
    }
    throw error;
  }
}

/** A Menivor Pro subscription option, priced by the App Store / Play Store. */
export interface ProPackageOption {
  identifier: string;
  /** Store-localised price, e.g. "$9.99" or "₺349,99". Never computed locally. */
  priceString: string;
  /** "month", "year", "week" or "" when the store gives no period. */
  period: string;
  title: string;
}

const proPackageCache = new Map<string, import("react-native-purchases").PurchasesPackage>();

function periodLabel(iso: string | null | undefined): string {
  switch (iso) {
    case "P1W":
      return "week";
    case "P1M":
      return "month";
    case "P3M":
      return "3 months";
    case "P6M":
      return "6 months";
    case "P1Y":
      return "year";
    default:
      return "";
  }
}

/** Load the current offering's Pro packages with store prices. */
export async function getProPackages(): Promise<ProPackageOption[]> {
  if (configuredApiKey === null) {
    throw new Error("In-app purchases are not configured for this build.");
  }
  const offerings = await Purchases.getOfferings();
  const packages = offerings.current?.availablePackages ?? [];
  proPackageCache.clear();
  return packages.map((pkg) => {
    proPackageCache.set(pkg.identifier, pkg);
    return {
      identifier: pkg.identifier,
      priceString: pkg.product.priceString,
      period: periodLabel(pkg.product.subscriptionPeriod),
      title: pkg.product.title,
    };
  });
}

/** Buy one Pro package. Resolves with fresh customer info; throws on cancel. */
export async function purchaseProPackage(identifier: string): Promise<CustomerInfo> {
  const pkg = proPackageCache.get(identifier);
  if (!pkg) throw new Error("This plan is no longer available. Refresh and try again.");
  try {
    const result = await Purchases.purchasePackage(pkg);
    return result.customerInfo;
  } catch (error) {
    if (
      error &&
      typeof error === "object" &&
      (error as { userCancelled?: unknown }).userCancelled === true
    ) {
      throw new StorePurchaseCancelledError();
    }
    throw error;
  }
}
