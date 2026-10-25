import type { Metadata } from "next";

export const metadata: Metadata = { title: "Reference graph" };

export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children;
}
