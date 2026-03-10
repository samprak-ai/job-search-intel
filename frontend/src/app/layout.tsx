import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Sam's Work Alignment",
  description: "Job search intelligence platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-gray-50 min-h-screen`}
      >
        <nav className="bg-white border-b border-gray-200 px-6 py-3">
          <div className="max-w-7xl mx-auto flex items-center gap-6">
            <Link href="/" className="text-lg font-bold text-gray-900">
              Sam's Work Alignment
            </Link>
            <div className="flex gap-4 text-sm">
              <Link
                href="/dashboard"
                className="text-gray-600 hover:text-gray-900"
              >
                Dashboard
              </Link>
              <Link
                href="/companies"
                className="text-gray-600 hover:text-gray-900"
              >
                Companies
              </Link>
            </div>
          </div>
        </nav>
        <div className="max-w-7xl mx-auto">{children}</div>
      </body>
    </html>
  );
}
