import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CogniFlow",
  description:
    "A tutor that changes its own objective when it works out why you are failing.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <main>{children}</main>
      </body>
    </html>
  );
}
