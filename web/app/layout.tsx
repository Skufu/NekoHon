import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NekoHon — Local Book Companion",
  description: "Local-first book companion with marginalia reader and grounded intelligence.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" data-theme="night" data-pen="vermilion" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
