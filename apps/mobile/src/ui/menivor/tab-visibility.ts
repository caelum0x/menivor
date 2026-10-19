/**
 * expo-router turns a tab's `href: null` into `tabBarItemStyle: { display:
 * "none" }`. The default tab bar honours it; Menivor's custom ReelTabBar uses
 * this check so a hidden tab is not drawn.
 */
type StyleLike = unknown;

function hasDisplayNone(style: StyleLike): boolean {
  if (Array.isArray(style)) return style.some(hasDisplayNone);
  return (
    typeof style === "object" &&
    style !== null &&
    (style as { display?: unknown }).display === "none"
  );
}

export function isTabHidden(options: { tabBarItemStyle?: StyleLike }): boolean {
  return hasDisplayNone(options.tabBarItemStyle);
}
