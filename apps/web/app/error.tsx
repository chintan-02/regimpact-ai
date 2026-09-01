"use client";

export default function ErrorBoundary({ reset }: { error: Error; reset: () => void }) {
  return (
    <main>
      <section className="masthead">
        <div><p className="eyebrow">WORKSPACE FAILURE</p><h1>Unable to load RegImpact</h1></div>
      </section>
      <section className="statusMessage error">
        The workspace encountered an unexpected error. <button onClick={reset}>Try again</button>
      </section>
    </main>
  );
}
