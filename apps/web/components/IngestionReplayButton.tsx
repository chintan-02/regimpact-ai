"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export function IngestionReplayButton({ jobId }: { jobId: string }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function replay() {
    setPending(true);
    setError(null);
    const response = await fetch(`/api/ingestions/${jobId}/replay`, { method: "POST" });
    if (!response.ok) {
      const payload = (await response.json()) as { detail?: string };
      setError(payload.detail ?? "Replay failed");
      setPending(false);
      return;
    }
    router.refresh();
    setPending(false);
  }
  return <><button className="tableAction" onClick={replay} disabled={pending}>{pending ? "Replaying…" : "Replay"}</button>{error && <small className="tableSub errorText">{error}</small>}</>;
}
