const STEPS = [
  {
    number: "01",
    title: "Paste any link",
    body: "Your site, app store page or a post. Menivor reads the page and writes from what is really there.",
  },
  {
    number: "02",
    title: "Pick a style",
    body: "Block-world gameplay, meme hook, anime, before and after. One click, no settings.",
  },
  {
    number: "03",
    title: "Get three reels",
    body: "Three 9:16 versions with different opening hooks, voiced and captioned. Keep the one that wins.",
  },
] as const;

/** How it works, in three steps. Anchored at #how-it-works. */
export function ThreeSteps() {
  return (
    <section id="how-it-works" className="scroll-mt-20 border-b border-white/[0.06]">
      <div className="container py-16 lg:py-20">
        <p className="kicker text-muted-foreground">How it works</p>
        <h2 className="mt-3 max-w-xl text-display font-bold">One link in, three reels out</h2>
        <ol className="mt-10 grid gap-4 md:grid-cols-3">
          {STEPS.map((step) => (
            <li key={step.number} className="glass-subtle rounded-2xl p-5">
              <p className="kicker text-primary">{step.number}</p>
              <h3 className="mt-3 text-lg font-semibold text-foreground">{step.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{step.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
