import type { Metadata } from "next";
import { JetBrains_Mono, Space_Grotesk } from "next/font/google";
import "./globals.css";

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-display",
});

const jetbrainsMono = JetBrains_Mono({
  weight: ["300", "400", "500", "700"],
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:7860"),
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
      <body className={`${spaceGrotesk.variable} ${jetbrainsMono.variable} font-sans antialiased`}>
        {children}
      </body>
    </html>
  );
}
