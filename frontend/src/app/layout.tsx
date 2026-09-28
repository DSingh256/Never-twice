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
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
