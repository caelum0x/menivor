import { permanentRedirect } from "next/navigation";

/** Short alias: `/contract` is the Creator Contract. */
export default function ContractAliasPage() {
  permanentRedirect("/creator-contract");
}
