import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Never Twice — Black Box Archive",
  description:
    "A deployment gate powered by organizational memory: every verdict cites the incidents it learned from.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link
          rel="icon"
          href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' fill='%23100e0c'/%3E%3Crect x='3' y='5' width='10' height='6' fill='none' stroke='%23f59e0b' stroke-width='1.4'/%3E%3Ccircle cx='11' cy='8' r='1.1' fill='%23f59e0b'/%3E%3C/svg%3E"
        />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
