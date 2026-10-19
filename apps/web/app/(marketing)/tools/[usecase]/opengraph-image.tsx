import { getUseCase, USE_CASE_SLUGS } from "@/lib/seo";
import { renderOgImage, OG_SIZE, OG_CONTENT_TYPE } from "@/lib/seo/og";

/** Pre-generate a card per use case so the route is statically known. */
export function generateStaticParams(): Array<{ usecase: string }> {
  return USE_CASE_SLUGS.map((usecase) => ({ usecase }));
}

export const alt = "Menivor tool";
export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

interface ImageProps {
  readonly params: { usecase: string };
}

/**
 * Dynamic OG card for `/tools/{usecase}` — renders the tool title on the brand
 * background. Params are passed by Next as a resolved object.
 */
export default function Image({ params }: ImageProps) {
  const useCase = getUseCase(params.usecase);
  const title = useCase?.title ?? "AI video tools";
  return renderOgImage({
    eyebrow: "Menivor · Tools",
    title,
    footer: "menivor.com · make your first reel free",
  });
}
