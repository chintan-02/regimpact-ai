export default function Loading() {
  return (
    <main aria-busy="true" aria-label="Loading regulatory workspace">
      <section className="masthead">
        <div>
          <p className="eyebrow">REGULATORY INTELLIGENCE</p>
          <h1 className="skeleton">Loading register</h1>
          <p className="lede">Retrieving version lineage and detected changes…</p>
        </div>
      </section>
      <section className="statusMessage">Connecting to the RegImpact evidence ledger.</section>
    </main>
  );
}
