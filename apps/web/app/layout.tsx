import "./globals.css";
import type { Metadata } from "next";

import { AppErrorBoundary } from "@/components/system/app-error-boundary";
import { SystemSettingsProvider } from "@/components/system/system-settings-provider";

export const metadata: Metadata = {
  title: "GremlinBoard",
  description: "Modular widget runtime board for OpenClaw.",
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
