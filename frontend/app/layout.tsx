import "./globals.css";

export const metadata = {
  title: "Adaptive Agent Workflow",
  description: "Dynamic Adaptive AI Agent Workflow",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-Hant">
      <body>{children}</body>
    </html>
  );
}
