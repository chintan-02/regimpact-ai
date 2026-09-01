"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

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
  return (
    <header className="commandRail">
      <Link className="brand" href="/">
        REGIMPACT <span>/ CONTROL ROOM</span>
      </Link>
      <nav aria-label="Primary navigation">
        {navigation.map(([href, label]) => (
          <Link className={pathname === href || (href !== "/" && pathname.startsWith(`${href}/`)) ? "active" : ""} href={href} key={href}>
            {label}
          </Link>
        ))}
      </nav>
      <div className="organization">Northstar Energy · Analyst</div>
    </header>
  );
}
