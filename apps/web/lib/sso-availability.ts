/**
 * MN7a: single sign-on is not sold yet (real SSO ships with MN7b). Until
 * `NEXT_PUBLIC_MENIVOR_SSO_ENABLED=1`, the SSO & SCIM settings are left out of
 * the navigation and `/settings/sso` shows a "contact sales" card instead of
 * the configuration forms. The forms stay in the code behind this flag.
 */
export const SSO_ENABLED = process.env.NEXT_PUBLIC_MENIVOR_SSO_ENABLED === "1";

/** The inbox that answers Enterprise and SSO questions. */
export const SSO_SALES_EMAIL = "hello@menivor.com";

export const SSO_SETTINGS_HREF = "/settings/sso";

/** Drop the SSO settings link from a list of links while SSO is off. */
export function withoutHiddenSso<T extends { readonly href: string }>(
  items: readonly T[],
  enabled: boolean = SSO_ENABLED,
): T[] {
  return enabled ? [...items] : items.filter((item) => item.href !== SSO_SETTINGS_HREF);
}
