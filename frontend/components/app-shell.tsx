"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const items = [
  ["Command center", "/"],
  ["Cases", "/cases"],
  ["Analytics", "/analytics"],
  ["Escalations", "/escalations"],
  ["Policies", "/policies"],
  ["Integrations", "/integrations"],
  ["Simulator", "/simulator"],
  ["Audit trail", "/audit"],
];

export function AppShell({ children, title }: Readonly<{ children: React.ReactNode; title: string }>) {
  const pathname = usePathname();
  const router = useRouter();
  const [user] = useState<{ name: string; role: string } | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      const storedUser = window.localStorage.getItem("recoverx_user");
      return storedUser ? JSON.parse(storedUser) as { name: string; role: string } : null;
    } catch {
      return null;
    }
  });
  useEffect(() => {
    if (!window.localStorage.getItem("recoverx_access_token")) {
      router.replace("/login");
      return;
    }
  }, [router]);
  return <main className="app-shell">
    <aside className="sidebar">
      <Link className="brand" href="/"><span className="brand-mark">R</span><span>recover<span className="brand-x">X</span></span></Link>
      <div className="workspace-switcher"><span className="workspace-avatar">RX</span><span><b>RecoverX Demo</b><small>Revenue operations</small></span></div>
      <nav className="nav-list" aria-label="Main navigation">
        {items.map(([label, href]) => <Link key={href} href={href} className={`nav-item ${pathname === href || (href !== "/" && pathname.startsWith(href)) ? "active" : ""}`}><span className="nav-icon">{label === "Cases" ? "◫" : label === "Analytics" ? "◒" : label === "Escalations" ? "!" : label === "Policies" ? "⌘" : label === "Integrations" ? "◈" : label === "Simulator" ? "▷" : label === "Audit trail" ? "≡" : "⌁"}</span>{label}</Link>)}
      </nav>
      <div className="sidebar-bottom"><div className="user-chip"><span className="user-avatar">RX</span><span><b>{user?.name ?? "RecoverX operator"}</b><small>{user?.role ?? "Administrator"}</small></span></div></div>
    </aside>
    <section className="content">
      <header className="topbar"><div className="mobile-brand"><span className="brand-mark">R</span> recover<span className="brand-x">X</span></div><div className="breadcrumb">Revenue operations <span>/</span> {title}</div><div className="top-actions"><div className="top-avatar">{user?.name?.slice(0, 2).toUpperCase() ?? "RX"}</div></div></header>
      <div className="page-wrap">{children}</div>
    </section>
  </main>;
}
