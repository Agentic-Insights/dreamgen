import type { Metadata } from "next";
import { JetBrains_Mono, IBM_Plex_Sans } from "next/font/google";
import "./globals.css";

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

const ibmPlexSans = IBM_Plex_Sans({
  weight: ["300", "400", "500", "600", "700"],
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "DreamGen — Agentic Insights",
  description: "AI-powered continuous image generation system with dynamic prompt enhancement",
  openGraph: {
    title: "DreamGen — Agentic Insights",
    description: "AI-powered continuous image generation system",
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
    <html lang="en" className="dark antialiased">
      <body className={`${ibmPlexSans.variable} ${jetbrainsMono.variable} font-sans flex flex-col min-h-screen`}>
        {children}
      </body>
    </html>
  );
}
