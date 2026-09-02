"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

type SessionUser = {
  organization_name: string;
  display_name: string;
  role: string;
};

const primaryNavigation = [
  ["/", "Changes"],
  ["/obligations", "Obligations"],
  ["/review", "Reviews"],
  ["/workflows", "Workflows"],
];

const managementNavigation = [["/controls", "Controls"], ["/sources", "Sources"], ["/ingestions", "Ingestion"]];

function active(pathname: string, href: string) {
  return pathname === href || (href !== "/" && pathname.startsWith(`${href}/`));
}

export function CommandRail() {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [demoEnabled, setDemoEnabled] = useState(false);

  useEffect(() => {
    if (pathname === "/login") return;
    fetch("/api/auth/me", { cache: "no-store" })
      .then((response) => {
        if (response.status === 401) {
          router.replace("/login");
          return null;
        }
        return response.ok ? response.json() : null;
      })
      .then((value: SessionUser | null) => setUser(value))
      .catch(() => setUser(null));
    fetch("/api/auth/demo-status", { cache: "no-store" })
      .then((response) => response.json())
      .then((value: { enabled?: boolean }) => setDemoEnabled(Boolean(value.enabled)))
      .catch(() => setDemoEnabled(false));
  }, [pathname, router]);

  if (pathname === "/login") return null;

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
    router.refresh();
  }
  async function switchAccount() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login?switch=1");
    router.refresh();
  }
  const allNavigation = [...primaryNavigation, ...managementNavigation, ...(user?.role === "admin" ? [["/operations", "Operations"]] : [])];
  return (
    <header className="commandRail">
      <Link className="brand" href="/">
        REGIMPACT <span>/ CONTROL ROOM</span>
      </Link>
      <nav className="desktopNavigation" aria-label="Primary navigation">
        {primaryNavigation.map(([href, label]) => (
          <Link className={active(pathname, href) ? "active" : ""} href={href} key={href}>
            {label}
          </Link>
        ))}
        <details className={`navDropdown ${managementNavigation.some(([href]) => active(pathname, href)) ? "active" : ""}`}><summary>Manage</summary><div>{managementNavigation.map(([href, label]) => <Link className={active(pathname, href) ? "active" : ""} href={href} key={href}>{label}</Link>)}</div></details>
        {user?.role === "admin" && <Link className={active(pathname, "/operations") ? "active" : ""} href="/operations">Operations</Link>}
      </nav>
      <details className="mobileNavigation"><summary aria-label="Open navigation">Menu</summary><nav aria-label="Mobile navigation">{allNavigation.map(([href, label]) => <Link className={active(pathname, href) ? "active" : ""} href={href} key={href}>{label}</Link>)}</nav></details>
      <div className="sessionIdentity">
        <details className="accountMenu"><summary><span>{user?.organization_name ?? "Authenticated session"}</span><small>{user?.role ?? "Loading identity"}</small></summary><div><p><b>{user?.display_name}</b><span>{user?.role}</span></p>{demoEnabled && <button onClick={switchAccount} type="button">Switch demo account</button>}<button onClick={logout} type="button">Sign out</button></div></details>
      </div>
    </header>
  );
}
