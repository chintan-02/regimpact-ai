export function StatusMessage({ type, children }: { type: "error" | "empty"; children: React.ReactNode }) {
  return (
    <section className={`statusMessage ${type}`} role={type === "error" ? "alert" : "status"}>
      <span>{type === "error" ? "SERVICE NOTICE" : "NO RECORDS"}</span>
      <p>{children}</p>
    </section>
  );
}
