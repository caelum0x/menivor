import Link from "next/link";
import type { Storefront as StorefrontData, TitleCard } from "./api";

function Card({ handle, card }: Readonly<{ handle: string; card: TitleCard }>) {
  return (
    <Link href={`/c/${encodeURIComponent(handle)}/${encodeURIComponent(card.id)}`} className="block">
      {card.artwork_url ? (
        <img src={card.artwork_url} alt="" loading="lazy" className="aspect-[9/16] w-full rounded-xl object-cover" />
      ) : (
        <div className="aspect-[9/16] w-full rounded-xl bg-muted" />
      )}
      <span className="mt-1 block text-sm font-medium">{card.title}</span>
      {!card.available_here ? <span className="block text-xs text-muted-foreground">Not available in your country</span> : null}
    </Link>
  );
}

/** Grid, rails or course layout; brand colour on the title bar. Server-rendered, no player until a title opens. */
export function Storefront({ data }: Readonly<{ data: StorefrontData }>) {
  const accent = data.brand_colors[0];
  const grid = <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{data.titles.map((t) => <li key={t.id}><Card handle={data.handle} card={t} /></li>)}</ul>;
  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      <header className="mb-6 border-b pb-4" style={accent ? { borderColor: accent } : undefined}>
        <h1 className="text-2xl font-semibold">{data.title}</h1>
        {data.tagline ? <p className="text-sm text-muted-foreground">{data.tagline}</p> : null}
      </header>
      {data.layout === "grid" ? grid : null}
      {data.layout === "rails"
        ? data.rails.map((rail) => (
            <section key={rail.id} aria-label={rail.title} className="mb-8">
              <h2 className="mb-2 text-lg font-semibold">{rail.title}</h2>
              <ul className="flex gap-3 overflow-x-auto pb-2">
                {rail.items.map((t) => <li key={t.id} className="w-36 shrink-0"><Card handle={data.handle} card={t} /></li>)}
              </ul>
            </section>
          ))
        : null}
      {data.layout === "course"
        ? data.series.map((series) => (
            <section key={series.id} aria-label={series.title} className="mb-8">
              <h2 className="mb-2 text-lg font-semibold">{series.title}</h2>
              <ol className="space-y-2">
                {series.episodes.map((t, i) => (
                  <li key={t.id}><Link className="underline" href={`/c/${encodeURIComponent(data.handle)}/${encodeURIComponent(t.id)}`}>{`${i + 1}. ${t.title}`}</Link></li>
                ))}
              </ol>
            </section>
          ))
        : null}
      {data.layout !== "grid" && data.rails.length === 0 && data.series.length === 0 ? grid : null}
    </main>
  );
}
