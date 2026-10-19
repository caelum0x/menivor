/**
 * UI Kit barrel — re-exports all primitive components.
 *
 * Import from here: `import { Button, Card, Screen } from "@/components/ui";`
 */

export { Avatar, type AvatarProps, type AvatarSize } from "./Avatar";
export { Badge, type BadgeProps, type BadgeVariant } from "./Badge";
export {
  Button,
  type ButtonProps,
  type ButtonSize,
  type ButtonVariant,
} from "./Button";
export { Card, type CardProps } from "./Card";
export { Chip, type ChipProps } from "./Chip";
export { Icon, type IconName, type IconProps } from "./Icon";
export { EmptyState, type EmptyStateProps } from "./EmptyState";
export { ErrorState, type ErrorStateProps } from "./ErrorState";
export {
  DateField,
  type DateFieldProps,
  FieldWrapper,
  NumberField,
  type NumberFieldProps,
  SelectField,
  type SelectFieldProps,
  type SelectOption,
  TextField,
  type TextFieldProps,
  ToggleField,
  type ToggleFieldProps,
} from "./Field";
export { Gallery, type GalleryProps } from "./Gallery";
export { Header, type HeaderProps } from "./Header";
export { ListRow, type ListRowProps } from "./ListRow";
export {
  Loading,
  type LoadingProps,
  Skeleton,
  SkeletonCard,
  type SkeletonCardProps,
  type SkeletonProps,
} from "./Loading";
export { MediaTile, type MediaTileProps } from "./MediaTile";
export { Modal, type ModalProps } from "./Modal";
export { Screen, type ScreenProps } from "./Screen";
export { SearchBar, type SearchBarProps } from "./SearchBar";
export { Segmented, type SegmentedItem, type SegmentedProps } from "./Segmented";
export { Sheet, type SheetProps } from "./Sheet";
export { StatTile, type StatTileProps } from "./StatTile";
export { Tabs, type TabItem, type TabsProps } from "./Tabs";
