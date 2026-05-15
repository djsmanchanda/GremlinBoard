import "./globals.css";
import type { Metadata } from "next";

import { AppErrorBoundary } from "@/components/system/app-error-boundary";
import { SystemSettingsProvider } from "@/components/system/system-settings-provider";

const iconSvg =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='12' fill='%2305070a'/%3E%3Cpath d='M14 18h36v28H14z' fill='none' stroke='%2367e8f9' stroke-width='4'/%3E%3Cpath d='M22 26h8v8h-8zM34 26h8v8h-8zM22 38h20' stroke='%23a7f3d0' stroke-width='4' stroke-linecap='round'/%3E%3C/svg%3E";

export const metadata: Metadata = {
  applicationName: "GremlinBoard",
  title: {
    default: "GremlinBoard",
    template: "%s | GremlinBoard",
  },
  description: "Modular widget runtime board with staged AI widget generation and monitored provider setup.",
  icons: {
    icon: [{ url: iconSvg, type: "image/svg+xml" }],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <SystemSettingsProvider />
        <AppErrorBoundary>{children}</AppErrorBoundary>
      </body>
    </html>
  );
}
