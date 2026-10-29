import type { Metadata } from "next";
import "./globals.css";
import "./nightfall.css";

export const metadata: Metadata = {
  title: "Nekohon — Local Book Companion",
  description: "A local-first reading room with a grounded companion that stays on this machine.",
  icons: {
    icon: "/nekohon-mark.svg",
  },
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
