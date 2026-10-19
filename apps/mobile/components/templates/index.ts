/**
 * Templates barrel — re-exports all screen templates.
 *
 * Import from here: `import { ListScreen, FormScreen } from "@/components/templates";`
 */

export { DetailScreen, type DetailScreenProps, type DetailSection } from "./DetailScreen";
export { FormScreen, type FormScreenProps } from "./FormScreen";
export {
  ListScreen,
  type FilterItem,
  type ListScreenProps,
} from "./ListScreen";
export {
  WizardScreen,
  type WizardContext,
  type WizardScreenProps,
  type WizardStep,
} from "./WizardScreen";
