import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Vehicle Collateral Risk Engine — Kenya",
  description: "B2B graph-native fraud detection platform for vehicle collateral risk in the Kenyan market. Hybrid entity resolution, loan-stacking detection, and anti-detection scraping architecture.",
  keywords: ["Kenya", "vehicle collateral", "risk engine", "fraud detection", "loan stacking", "entity resolution", "MFI", "SACCO", "Neo4j", "knowledge graph"],
  authors: [{ name: "Vehicle Collateral Risk Engine" }],
  icons: {
    icon: "https://z-cdn.chatglm.cn/z-ai/static/logo.svg",
  },
  openGraph: {
    title: "Vehicle Collateral Risk Engine — Kenya",
    description: "B2B graph-native fraud detection for vehicle collateral risk",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-background text-foreground`}
      >
        {children}
        <Toaster />
      </body>
    </html>
  );
}
