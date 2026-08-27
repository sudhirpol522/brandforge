import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BrandForge — Creative Intelligence",
  description: "Human-governed campaign creation, evaluation and multimodal ranking"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
