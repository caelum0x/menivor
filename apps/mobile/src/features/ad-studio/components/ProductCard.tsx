/** Extracted product facts: images, price, rating and key features. */

import { Image, Linking, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { Badge, Icon } from "@/components/ui";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

import { SOURCE_LABELS, formatPrice, type Product } from "../api";

export interface ProductCardProps {
  readonly product: Product;
  /** Overrides the remote image list (e.g. the project's imported images). */
  readonly images?: readonly string[];
}

export function ProductCard({ product, images }: ProductCardProps) {
  const price = formatPrice(product.price, product.currency, product.language);
  const original = formatPrice(product.original_price, product.currency, product.language);
  const gallery = (images ?? product.images).filter((src) => /^https?:\/\//i.test(src)).slice(0, 6);
  return (
    <View style={styles.card}>
      {gallery.length === 0 ? (
        <Text style={styles.muted}>No product images found.</Text>
      ) : (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.gallery}>
          {gallery.map((src, index) => (
            <Image
              key={`${src}-${index}`}
              source={{ uri: src }}
              style={styles.image}
              resizeMode="contain"
              accessibilityLabel={`${product.title} image ${index + 1}`}
            />
          ))}
        </ScrollView>
      )}
      <View style={styles.badges}>
        <Badge label={SOURCE_LABELS[product.source] ?? product.source} />
        {product.brand ? <Badge label={product.brand} /> : null}
      </View>
      <Text style={styles.title}>{product.title}</Text>
      {price ? (
        <Text style={styles.price}>
          {price}
          {original ? <Text style={styles.original}>  {original}</Text> : null}
        </Text>
      ) : null}
      {product.rating ? (
        <View style={styles.row}>
          <Icon name="star-outline" size={14} color={colors.textSecondary} />
          <Text style={styles.muted}>
            {product.rating.toFixed(1)} / 5
            {product.review_count ? ` from ${product.review_count} reviews` : ""}
          </Text>
        </View>
      ) : null}
      {product.bullets.length > 0 ? (
        <View style={styles.bullets}>
          {product.bullets.slice(0, 5).map((bullet) => (
            <Text key={bullet} style={styles.muted}>
              {"•"} {bullet}
            </Text>
          ))}
        </View>
      ) : product.description ? (
        <Text style={styles.muted}>{product.description.slice(0, 280)}</Text>
      ) : null}
      {product.url ? (
        <Pressable
          onPress={() => void Linking.openURL(product.url).catch(() => undefined)}
          accessibilityRole="link"
          style={styles.row}
          hitSlop={8}
        >
          <Text style={styles.link}>View product page</Text>
          <Icon name="open-outline" size={14} color={colors.accent} />
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.sm,
  },
  gallery: { gap: spacing.sm },
  image: {
    width: 96,
    height: 96,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceMuted,
  },
  badges: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  title: { color: colors.textPrimary, fontSize: typeScale.subheading, fontWeight: "700" },
  price: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "700" },
  original: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    fontWeight: "400",
    textDecorationLine: "line-through",
  },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  bullets: { gap: 2 },
  muted: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  link: { color: colors.accent, fontSize: typeScale.caption, fontWeight: "700" },
});
