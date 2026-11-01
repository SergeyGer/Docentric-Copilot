import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { AppFooter } from "@/components/app-footer";
import { AppHeader } from "@/components/app-header";
import { CompatibilityNotice } from "@/components/compatibility-notice";

import "./globals.css";

export const metadata: Metadata = {
  title: "Docentric Copilot · Template workspace",
  description:
    "Schema-aware prompt-to-template engineering: upload a DDSP source, plan and review a validated Template IR, preview HTML and compile a deterministic generic DOCX.",
  applicationName: "Docentric Copilot",
  keywords: [
    "Docentric Copilot",
    "DDSP",
    "template engineering",
    "DOCX",
    "schema mapping",
  ],
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#f8fafc",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-background font-sans text-foreground">
        <a href="#workspace" className="skip-link">
          Skip to workspace
        </a>
        <div className="flex min-h-screen flex-col">
          <AppHeader />
          <CompatibilityNotice />
          <main id="workspace" className="flex-1">
            {children}
          </main>
          <AppFooter />
        </div>
      </body>
    </html>
  );
}
