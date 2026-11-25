import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { DevAuthBanner } from "@/components/dev-auth-banner";
import { Toaster } from "@/components/ui/sonner";
import { AppAuthProvider } from "@/lib/auth/provider";
import { authProvider, clerkPublishableKey } from "@/lib/env";
import { MeProvider } from "@/lib/hooks";

import "./globals.css";

const geistSans = Geist({ variable: "--font-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Ticket Resolver",
  description: "Policy-grounded answers to support tickets",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  const app = (
    <AppAuthProvider>
      <MeProvider>
        <DevAuthBanner />
        {children}
        <Toaster richColors position="top-right" />
      </MeProvider>
    </AppAuthProvider>
  );

  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col bg-background text-foreground">
        {/* Rendered only with a key: without one, Clerk would start "keyless" mode. */}
        {authProvider === "clerk" ? (
          <ClerkProvider publishableKey={clerkPublishableKey}>{app}</ClerkProvider>
        ) : (
          app
        )}
      </body>
    </html>
  );
}
