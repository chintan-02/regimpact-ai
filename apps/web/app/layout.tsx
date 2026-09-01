import type { Metadata } from "next";
import { CommandRail } from "../components/CommandRail";
import "./styles.css";

export const metadata: Metadata = {
  title: "RegImpact AI",
  description: "Regulatory change impact and controls assurance platform",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <CommandRail />
        {children}
      </body>
    </html>
  );
}
