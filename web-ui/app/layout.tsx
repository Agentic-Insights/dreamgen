import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import "./globals.css";

const jetbrainsMono = JetBrains_Mono({
  weight: ["300", "400", "500", "700"],
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono"
});

export const metadata: Metadata = {
  title: "DreamGen — Recurring Local Image Generator",
  description: "Generate images locally on a recurring rhythm with simple prompts, entropy plugins, and a lightweight fallback model.",
  openGraph: {
    title: "DreamGen — Recurring Local Image Generator",
    description: "Generate images locally on a recurring rhythm.",
    images: ["/logo_mark.png"],
    siteName: "Agentic Insights",
    type: "website",
  },
  icons: {
    icon: "/logo_mark.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className={`${jetbrainsMono.className} antialiased`}>
        {children}
      </body>
    </html>
  );
}
