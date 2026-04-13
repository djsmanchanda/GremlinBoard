import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "GremlinBoard",
  description: "Modular widget runtime board for OpenClaw.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
