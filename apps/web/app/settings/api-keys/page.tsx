import { redirect } from "next/navigation";

/**
 * `/settings/api-keys` is kept as a stable alias: personal API keys are
 * managed at the canonical `/account/api-keys` page.
 */
export default function SettingsApiKeysPage(): never {
  redirect("/account/api-keys");
}
