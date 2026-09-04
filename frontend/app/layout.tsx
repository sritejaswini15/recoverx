import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RecoverX | Revenue Recovery Control Plane",
  description: "AI-driven revenue recovery operations for Razorpay merchants.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en"><body>{children}</body></html>
  );
}
