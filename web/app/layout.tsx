import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Ask this book",
  description: "Ask the book. It answers only from its own pages.",
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
