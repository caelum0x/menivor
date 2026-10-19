import { initials } from "./api";

/** The actor's generated face, or soft initials until a face exists. */
export function ActorAvatar({ name, url, size = 56 }: { name: string; url: string; size?: number }) {
  if (url) {
    // eslint-disable-next-line @next/next/no-img-element -- remote generated media, sizes vary
    return <img src={url} alt={`${name} (synthetic actor)`} width={size} height={size} className="rounded-full object-cover" />;
  }
  return (
    <span
      aria-hidden
      style={{ width: size, height: size }}
      className="inline-flex shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/[0.06] text-sm font-semibold text-muted-foreground"
    >
      {initials(name)}
    </span>
  );
}
