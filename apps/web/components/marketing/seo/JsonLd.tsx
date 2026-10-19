/**
 * Renders a JSON-LD structured-data document into a <script> tag. Server
 * component — the object is serialised at render time, never on the client.
 */
interface JsonLdProps {
  readonly data: Record<string, unknown>;
}

export function JsonLd({ data }: JsonLdProps) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  );
}
