"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const SAMPLES = [
  { tag: "EMPLOYMENT ACT 1955", q: "Compare overtime entitlements between Section 60A and the 2022 amendments." },
  { tag: "COMPANIES ACT 2016", q: "What are directors' duties under §213 and how have courts interpreted them?" },
  { tag: "CONTRACTS ACT 1950", q: "Trace the doctrine of frustration through Malaysian case law." },
  { tag: "PDPA 2010", q: "Summarise consent requirements for cross-border data transfers." },
];

const FAQS = [
  { q: "Which Acts does Locus currently cover?", a: "All Federal Acts published by the Attorney General's Chambers, including amendments through April 2026. State enactments and subsidiary legislation are rolling out by jurisdiction." },
  { q: "How does Locus handle citations?", a: "Every claim is traced to a section, subsection, or paragraph. Hover any citation to read the source verbatim; click to open the full provision in the side panel." },
  { q: "Can I upload my own briefs and contracts?", a: "Yes. Documents stay within your workspace, are never used for training, and are searchable alongside the statutory corpus during a session." },
  { q: "Is Locus a substitute for legal advice?", a: "No. Locus is a research instrument for qualified practitioners. Output should be reviewed before relying on it in advice or filings." },
];

const SUGGESTED = [
  { label: "EA 1955 on gig workers", query: "Does the Employment Act 1955 apply to gig workers after the 2022 amendments?" },
  { label: "§346 oppression", query: "What constitutes oppression under §346 Companies Act 2016?" },
  { label: "Force majeure doctrine", query: "Force majeure under the Contracts Act 1950 — judicial treatment." },
];

const TRUST_STATS = [
  { num: "1,200", suffix: "+", lbl: "FEDERAL ACTS INDEXED" },
  { num: "1.2", suffix: "M", lbl: "PROVISIONS TRACED" },
  { num: "2026", suffix: ".04", lbl: "LAST CONSOLIDATED" },
  { num: "100", suffix: "%", lbl: "CITED TO SOURCE" },
];

function CompassMark({ size = 22, ticks = true }: { size?: number; ticks?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none" className="chamber-text-bronze shrink-0">
      <circle cx="14" cy="14" r="13" stroke="currentColor" strokeWidth="1" />
      <circle cx="14" cy="14" r="3" fill="currentColor" />
      {ticks && (
        <>
          <line x1="14" y1="1" x2="14" y2="6" stroke="currentColor" strokeWidth="1" />
          <line x1="14" y1="22" x2="14" y2="27" stroke="currentColor" strokeWidth="1" />
        </>
      )}
    </svg>
  );
}

export default function Landing() {
  const [query, setQuery] = useState("");
  const [openFaq, setOpenFaq] = useState(-1);
  const router = useRouter();

  const handleResearch = () => {
    if (query.trim()) {
      router.push(`/workspace?q=${encodeURIComponent(query.trim())}`);
    } else {
      router.push("/workspace");
    }
  };

  return (
    <div className="relative w-full min-h-full px-4 pt-8 pb-16 md:px-16">

      {/* NAV */}
      <header className="grid landing-grid-nav items-center pb-7 border-b border-(--rule)">
        <div className="flex items-center gap-2.5">
          <CompassMark />
          <span className="font-sans font-semibold text-[13px] tracking-[0.32em] chamber-text-ink">LOCUS</span>
        </div>

        <nav className="hidden md:flex gap-8 justify-center">
          <a href="#capabilities" className="chamber-text-ink-2 no-underline text-[13px] tracking-[0.04em] transition-colors duration-150 hover:text-(--bronze)">Capabilities</a>
          <a href="#faq" className="chamber-text-ink-2 no-underline text-[13px] tracking-[0.04em] transition-colors duration-150 hover:text-(--bronze)">Coverage</a>
          <a href="#faq" className="chamber-text-ink-2 no-underline text-[13px] tracking-[0.04em] transition-colors duration-150 hover:text-(--bronze)">Method</a>
          <a href="#faq" className="chamber-text-ink-2 no-underline text-[13px] tracking-[0.04em] transition-colors duration-150 hover:text-(--bronze)">Pricing</a>
        </nav>

        <div className="flex items-center gap-[18px] justify-end">
          <Link href="/workspace" className="chamber-text-ink-2 no-underline text-[13px] transition-colors duration-150 hover:text-(--ink) hidden sm:block">Sign in</Link>
          <Link
            href="/workspace"
            className="inline-flex items-center gap-2 px-[18px] py-2.5 bg-(--bronze) text-(--bg) rounded no-underline text-[12px] font-semibold tracking-[0.08em] uppercase transition-colors duration-150 hover:bg-(--ink)"
          >
            Request access <span>→</span>
          </Link>
        </div>
      </header>

      {/* HERO */}
      <section className="py-24 border-b border-(--rule)">
        {/* Eyebrow */}
        <div className="flex items-center gap-3.5 chamber-text-ink-3 mb-12">
          <span className="font-mono text-[11px] tracking-[0.12em] uppercase">/MY · 002</span>
          <span className="w-6 h-px bg-(--rule)" />
          <span className="font-mono text-[11px] tracking-[0.12em] uppercase">PRIVATE BETA</span>
          <span className="w-6 h-px bg-(--rule)" />
          <span className="font-mono text-[11px] tracking-[0.12em] uppercase">CONSOLIDATED 2026.04</span>
        </div>

        {/* H1 */}
        <h1 className="font-serif font-light text-[clamp(48px,7vw,88px)] leading-[1.02] tracking-[-0.03em] chamber-text-ink m-0 mb-8 max-w-[18ch]">
          The Malaysian statute,<br />
          <span className="italic chamber-text-bronze">made navigable.</span>
        </h1>

        {/* Subtitle */}
        <p className="text-[17px] leading-[1.65] chamber-text-ink-2 max-w-[60ch] m-0 mb-14">
          Locus is a research instrument for advocates, in-house counsel and academics.
          It reads, cross-references, and cites the full corpus of Federal legislation
          so you can argue from primary sources, not summaries.
        </p>

        {/* Prompt */}
        <div className="grid landing-grid-prompt items-center bg-(--bg-2) border border-(--rule) rounded overflow-hidden max-w-[820px] transition-[border-color] duration-200 focus-within:border-(--bronze) focus-within:shadow-[0_0_0_1px_var(--bronze),0_24px_60px_-24px_rgba(194,168,120,0.18)]">
          <div className="px-[18px] chamber-text-bronze border-r border-(--rule) self-stretch flex items-center">
            <span className="font-mono text-[11px] tracking-[0.12em] uppercase">ASK ›</span>
          </div>
          <input
            className="border-none outline-none bg-transparent font-sans text-[16px] chamber-text-ink py-[22px] px-[18px] placeholder:text-(--ink-3)"
            placeholder="Begin with a section, a doctrine, or a question…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleResearch()}
          />
          <button
            onClick={handleResearch}
            className="inline-flex items-center gap-2 px-[22px] self-stretch bg-(--bronze) text-(--bg) border-none font-sans text-[12px] font-semibold tracking-[0.1em] uppercase cursor-pointer transition-colors duration-150 hover:bg-(--ink) whitespace-nowrap"
          >
            Research <span>→</span>
          </button>
        </div>

        {/* Suggested queries */}
        <div className="flex flex-wrap items-center gap-4 mt-5">
          <span className="font-mono text-[11px] tracking-[0.12em] uppercase chamber-text-ink-3">SUGGESTED</span>
          {SUGGESTED.map(({ label, query: q }) => (
            <button
              key={label}
              onClick={() => setQuery(q)}
              className="bg-transparent border border-(--rule) chamber-text-ink-2 font-[inherit] text-[12px] px-3 py-1.5 rounded-full cursor-pointer transition-all duration-150 hover:text-(--bronze) hover:border-(--bronze)"
            >
              {label}
            </button>
          ))}
        </div>

        {/* Trust stats */}
        <div className="grid landing-grid-trust gap-px bg-(--rule) mt-20 border border-(--rule)">
          {TRUST_STATS.map(({ num, suffix, lbl }) => (
            <div key={lbl} className="bg-(--bg) px-8 py-7">
              <div className="font-serif font-light text-[44px] chamber-text-ink leading-none tracking-[-0.02em]">
                {num}<span className="chamber-text-bronze italic text-[28px]">{suffix}</span>
              </div>
              <div className="font-mono text-[10px] chamber-text-ink-3 mt-3 tracking-[0.12em]">{lbl}</div>
            </div>
          ))}
        </div>
      </section>

      {/* CAPABILITIES /01 */}
      <section id="capabilities" className="border-b border-(--rule) pb-20">
        <div className="grid landing-grid-section gap-10 pt-20 pb-10 items-baseline">
          <span className="font-mono text-[12px] chamber-text-bronze tracking-[0.12em]">/01</span>
          <div>
            <h2 className="font-serif font-light text-[48px] leading-[1.1] tracking-[-0.025em] m-0 mb-4 chamber-text-ink">What you can ask</h2>
            <p className="text-[16px] chamber-text-ink-2 max-w-[56ch] m-0">
              A few prompts that show how Locus reasons across the corpus. Every answer arrives with the underlying provision attached.
            </p>
          </div>
        </div>

        <div className="grid landing-grid-cap gap-px bg-(--rule) border-t border-(--rule) border-b">
          {SAMPLES.map((s, i) => (
            <article
              key={i}
              className="bg-(--bg) px-9 py-8 grid landing-grid-cap-card gap-6 cursor-pointer transition-colors duration-200 hover:bg-(--bg-2)"
            >
              <div className="font-serif italic font-light text-[36px] chamber-text-bronze leading-none">{String(i + 1).padStart(2, "0")}</div>
              <div>
                <div className="font-mono text-[10px] chamber-text-ink-3 tracking-[0.12em] mb-3.5">{s.tag}</div>
                <p className="font-serif text-[22px] font-light leading-[1.35] chamber-text-ink m-0 mb-6 tracking-[-0.01em]">{s.q}</p>
                <div className="flex justify-between items-center pt-5 border-t border-(--rule-soft) chamber-text-ink-3">
                  <span className="font-mono text-[10px] tracking-[0.12em]">§ 4 SECTIONS · 12 CASES</span>
                  <span className="chamber-text-bronze font-mono text-[11px] tracking-[0.1em]">OPEN ↗</span>
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>

      {/* FAQ /02 */}
      <section id="faq" className="pb-16">
        <div className="grid landing-grid-section gap-10 pt-20 pb-10 items-baseline">
          <span className="font-mono text-[12px] chamber-text-bronze tracking-[0.12em]">/02</span>
          <div>
            <h2 className="font-serif font-light text-[48px] leading-[1.1] tracking-[-0.025em] m-0 chamber-text-ink">Questions, answered.</h2>
          </div>
        </div>

        <div className="border-t border-(--rule)">
          {FAQS.map((f, i) => (
            <div
              key={i}
              className="border-b border-(--rule) cursor-pointer transition-colors duration-150 hover:bg-(--bg-2)"
              onClick={() => setOpenFaq(openFaq === i ? -1 : i)}
            >
              <div className="grid landing-grid-faq-q gap-6 py-7 items-center">
                <span className="font-mono text-[11px] tracking-[0.12em] uppercase chamber-text-bronze">/{String(i + 1).padStart(2, "0")}</span>
                <span className={`font-serif text-[22px] font-light tracking-[-0.01em] transition-colors duration-150 ${openFaq === i ? "chamber-text-bronze" : "chamber-text-ink"}`}>
                  {f.q}
                </span>
                <span className="font-serif chamber-text-ink-3 text-right text-[22px] font-light">{openFaq === i ? "−" : "+"}</span>
              </div>
              {openFaq === i && (
                <div className="grid landing-grid-faq-q gap-6 pb-7">
                  <div className="col-start-2 text-[15px] leading-[1.65] chamber-text-ink-2">{f.a}</div>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* FOOTER */}
      <footer className="grid grid-cols-[1fr_auto] items-center pt-8 border-t border-(--rule)">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2.5">
            <CompassMark ticks={false} />
            <span className="font-sans font-semibold text-[13px] tracking-[0.32em] chamber-text-ink">LOCUS</span>
          </div>
          <span className="font-serif italic text-[14px] chamber-text-ink-2 font-light">A research instrument for the Malaysian Bar.</span>
        </div>
        <div className="flex gap-3 chamber-text-ink-3">
          <span className="font-mono text-[11px] tracking-[0.12em] uppercase">KUALA LUMPUR</span>
          <span className="font-mono text-[11px] tracking-[0.12em] uppercase">·</span>
          <span className="font-mono text-[11px] tracking-[0.12em] uppercase">MMXXVI</span>
        </div>
      </footer>
    </div>
  );
}
