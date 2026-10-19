/**
 * `@reelforge/ui-kit` — shared React components + design tokens for the web/
 * Electron surfaces, plus a framework-free `tokens.json` re-mapped by mobile and
 * the Rust/GPUI desktop so all four apps share one palette. Domain components
 * reuse `growth-analytics` etc. so metrics render identically to the backend.
 */
export * from "./tokens/index.js";
export * from "./format/index.js";
export { useDebounce } from "./hooks/useDebounce.js";

// primitives
export { Button, type ButtonProps, type ButtonVariant } from "./primitives/Button.js";
export { Card } from "./primitives/Card.js";
export { Badge, type BadgeTone } from "./primitives/Badge.js";
export { Divider } from "./primitives/Divider.js";
export { TextField, type TextFieldProps } from "./primitives/TextField.js";
export { TextArea, type TextAreaProps } from "./primitives/TextArea.js";
export { Toggle } from "./primitives/Toggle.js";
export { SegmentedControl } from "./primitives/SegmentedControl.js";
export { Chip, ChipRow } from "./primitives/Chip.js";
export { Pill } from "./primitives/Pill.js";
export { Stepper } from "./primitives/Stepper.js";

// feedback
export { Skeleton } from "./feedback/Skeleton.js";
export { ProgressBar } from "./feedback/ProgressBar.js";
export { EmptyState } from "./feedback/EmptyState.js";
export { ErrorState } from "./feedback/ErrorState.js";
export { LoadingState } from "./feedback/LoadingState.js";

// data
export { StatTile } from "./data/StatTile.js";
export { KeyValueRow } from "./data/KeyValueRow.js";
export { CreditText } from "./data/CreditText.js";
export { RelativeTime, relativeTime } from "./data/RelativeTime.js";

// domain (reuse the shared packages)
export { MoneyText } from "./domain/MoneyText.js";
export { PlatformIcon } from "./domain/PlatformIcon.js";
export { HookScoreGauge } from "./domain/HookScoreGauge.js";
export { BurnPreviewBadge } from "./domain/BurnPreviewBadge.js";
export { SafeZoneOverlay } from "./domain/SafeZoneOverlay.js";
export { RetentionCurveChart } from "./domain/RetentionCurveChart.js";
export { SegmentSlotBar, type Slot } from "./domain/SegmentSlotBar.js";
export { CircularProgress } from "./feedback/CircularProgress.js";
export { ListRow } from "./data/ListRow.js";
