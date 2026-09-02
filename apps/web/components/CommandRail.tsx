"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

type SessionUser = {
  organization_name: string;
  display_name: string;
  role: string;
};

const navigation = [
  ["/", "Change register"],
  ["/obligations", "Obligations"],
  ["/review", "Review queue"],
  ["/controls", "Controls"],
  ["/sources", "Sources"],
  ["/ingestions", "Ingestion"],
];

export function CommandRail() {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<SessionUser | null>(null);

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
  }, [pathname, router]);

  if (pathname === "/login") return null;

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
    router.refresh();
  }
  return (
    <header className="commandRail">
      <Link className="brand" href="/">
        REGIMPACT <span>/ CONTROL ROOM</span>
      </Link>
      <nav aria-label="Primary navigation">
        {[...navigation, ...(user?.role === "admin" ? [["/operations", "Operations"]] : [])].map(([href, label]) => (
          <Link className={pathname === href || (href !== "/" && pathname.startsWith(`${href}/`)) ? "active" : ""} href={href} key={href}>
            {label}
          </Link>
        ))}
      </nav>
      <div className="sessionIdentity">
        <span className="organization">
          {user ? `${user.organization_name} · ${user.role}` : "Authenticated session"}
        </span>
        <button className="logoutButton" onClick={logout} type="button">
          Sign out
        </button>
      </div>
    </header>
  );
}
