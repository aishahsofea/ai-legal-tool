"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

const SAMPLES = [
  {
    tag: "EMPLOYMENT ACT 1955",
    q: "Compare the overtime entitlements in Section 60A with the 2022 amendments.",
  },
  {
    tag: "COMPANIES ACT 2016",
    q: "Explain the statutory duties of directors under Section 213 and the related provisions.",
  },
  {
    tag: "CONTRACTS ACT 1950",
    q: "How does Section 57 treat an agreement that becomes impossible to perform?",
  },
  {
    tag: "PDPA 2010",
    q: "Summarise the statutory restrictions on transferring personal data outside Malaysia.",
  },
];

const FAQS = [
  {
    q: "Which sources does Locus currently cover?",
    a: "The current research corpus focuses on Federal Acts published through the Laws of Malaysia portal. State enactments, subsidiary legislation, and Case Law are not part of the v1 corpus.",
  },
  {
    q: "How does Locus handle citations?",
    a: "Legal answers link each cited provision to its Act, section, and official PDF page. The source map keeps the primary material beside the answer so it can be checked immediately.",
  },
  {
    q: "Can I ask in English or Bahasa Malaysia?",
    a: "Yes. Locus accepts English, Bahasa Malaysia, and code-switched queries. Citations retain the registered source language, including Acts available only in Bahasa Malaysia.",
  },
  {
    q: "Is Locus a substitute for legal advice?",
    a: "No. Locus is a research instrument for qualified practitioners. Its output should be reviewed against the cited primary sources before it is relied on in advice or filings.",
  },
];

const SUGGESTED = [
  {
    label: "EA 1955 on gig workers",
    query: "Does the Employment Act 1955 apply to gig workers after the 2022 amendments?",
  },
  {
    label: "Section 346 oppression",
    query: "What does Section 346 of the Companies Act 2016 say about oppression?",
  },
  {
    label: "Section 57 frustration",
    query: "How does Section 57 of the Contracts Act 1950 address frustration?",
  },
];

const TRUST_MARKERS = [
  { value: "Federal Acts", label: "PRIMARY-SOURCE CORPUS" },
  { value: "Section level", label: "PRECISE RETRIEVAL" },
  { value: "EN + BM", label: "BILINGUAL QUERIES" },
  { value: "Cited", label: "TRACEABLE ANSWERS" },
];

function CompassMark({ size = 24, ticks = true }: { size?: number; ticks?: boolean }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 28 28"
      fill="none"
      aria-hidden="true"
      className="shrink-0 text-(--accent)"
    >
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
    const trimmed = query.trim();
    router.push(trimmed ? `/workspace?q=${encodeURIComponent(trimmed)}` : "/workspace");
  };

  return (
    <div className="mx-auto min-h-full w-full max-w-[1440px] px-4 pb-16 pt-4 md:px-12 lg:px-16">
      <header className="landing-grid-nav grid h-[64px] items-center border-b border-(--line)">
        <div className="flex items-center gap-3">
          <CompassMark />
          <span className="text-xs font-semibold tracking-[0.24em] text-(--text)">LOCUS</span>
        </div>

        <nav className="hidden items-center justify-center gap-8 md:flex" aria-label="Primary navigation">
          <a href="#capabilities" className="text-sm text-(--text-muted) no-underline transition-colors duration-200 hover:text-(--accent)">Capabilities</a>
          <a href="#faq" className="text-sm text-(--text-muted) no-underline transition-colors duration-200 hover:text-(--accent)">Coverage</a>
          <a href="#faq" className="text-sm text-(--text-muted) no-underline transition-colors duration-200 hover:text-(--accent)">Method</a>
        </nav>

        <div className="flex items-center justify-end gap-4">
          <Link href="/workspace" className="hidden text-sm text-(--text-muted) no-underline transition-colors duration-200 hover:text-(--text) sm:block">
            Sign in
          </Link>
          <Link
            href="/workspace"
            className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-(--accent) px-4 py-2 text-xs font-semibold tracking-[0.04em] text-(--surface) no-underline shadow-[var(--shadow-soft)] transition-colors duration-200 hover:bg-(--accent-deep)"
          >
            Request access <span aria-hidden="true">→</span>
          </Link>
        </div>
      </header>

      <main>
        <section className="border-b border-(--line) py-16 lg:py-20">
          <div className="mb-8 flex flex-wrap items-center gap-3 text-(--text-subtle)">
            <span className="font-mono text-xs tracking-[0.12em]">MALAYSIA / FEDERAL ACTS</span>
            <span className="h-px w-8 bg-(--line)" />
            <span className="font-mono text-xs tracking-[0.12em]">PRIVATE BETA</span>
          </div>

          <h1 className="m-0 mb-6 max-w-[18ch] font-serif text-[clamp(40px,6vw,72px)] font-light leading-[1.04] tracking-[-0.03em] text-(--text)">
            The Malaysian statute,
            <br />
            <span className="italic text-(--accent)">made navigable.</span>
          </h1>

          <p className="m-0 mb-10 max-w-[60ch] text-base leading-7 text-(--text-muted)">
            A focused research workspace for advocates, in-house counsel, and academics.
            Ask a precise question, follow the governing provisions, and work outward from
            primary sources.
          </p>

          <div className="landing-grid-prompt grid max-w-[800px] items-center overflow-hidden rounded-xl border border-(--line) bg-(--surface) shadow-[var(--shadow-raised)] transition-[border-color,box-shadow] duration-200 focus-within:border-(--accent)">
            <div className="flex self-stretch items-center border-r border-(--line) px-4 text-(--accent)">
              <span className="font-mono text-xs tracking-[0.12em]">ASK ›</span>
            </div>
            <input
              className="border-none bg-transparent px-4 py-4 text-sm text-(--text) outline-none placeholder:text-(--text-subtle)"
              placeholder="Begin with an Act, section, or research question…"
              aria-label="Legal research question"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && handleResearch()}
            />
            <button
              type="button"
              onClick={handleResearch}
              className="inline-flex self-stretch items-center gap-2 whitespace-nowrap border-none bg-(--accent) px-5 text-xs font-semibold tracking-[0.08em] text-(--surface) transition-colors duration-200 hover:bg-(--accent-deep)"
            >
              Research <span aria-hidden="true">→</span>
            </button>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-2">
            <span className="mr-2 font-mono text-xs tracking-[0.12em] text-(--text-subtle)">SUGGESTED</span>
            {SUGGESTED.map(({ label, query: suggestedQuery }) => (
              <button
                type="button"
                key={label}
                onClick={() => setQuery(suggestedQuery)}
                className="min-h-9 rounded-full border border-(--line) bg-(--surface) px-3 py-2 text-xs text-(--text-muted) transition-colors duration-200 hover:border-(--accent-line) hover:bg-(--accent-tint) hover:text-(--accent)"
              >
                {label}
              </button>
            ))}
          </div>

          <div className="landing-grid-trust mt-12 grid gap-3">
            {TRUST_MARKERS.map(({ value, label }) => (
              <div key={label} className="rounded-xl border border-(--line-soft) bg-(--surface) px-4 py-4 shadow-[var(--shadow-soft)]">
                <div className="font-serif text-xl font-light tracking-[-0.02em] text-(--text)">{value}</div>
                <div className="mt-2 font-mono text-[10px] tracking-[0.12em] text-(--text-subtle)">{label}</div>
              </div>
            ))}
          </div>
        </section>

        <section id="capabilities" className="border-b border-(--line) py-16 lg:py-20">
          <div className="landing-grid-section mb-10 grid items-baseline gap-6">
            <span className="font-mono text-xs tracking-[0.12em] text-(--accent)">01 / RESEARCH</span>
            <div>
              <h2 className="m-0 mb-3 font-serif text-4xl font-light leading-[1.08] tracking-[-0.02em] text-(--text)">What you can ask</h2>
              <p className="m-0 max-w-[56ch] text-base leading-7 text-(--text-muted)">
                Start with a provision, amendment, or statutory question. Each answer keeps
                its supporting sections close enough to inspect without leaving the thread.
              </p>
            </div>
          </div>

          <div className="landing-grid-cap grid gap-3">
            {SAMPLES.map((sample, index) => (
              <button
                type="button"
                key={sample.q}
                onClick={() => router.push(`/workspace?q=${encodeURIComponent(sample.q)}`)}
                className="landing-grid-cap-card grid gap-4 rounded-xl border border-(--line) bg-(--surface) px-5 py-5 text-left shadow-[var(--shadow-soft)] transition-[border-color,transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:border-(--accent-line) hover:shadow-[var(--shadow-raised)]"
              >
                <div className="font-serif text-3xl font-light italic leading-none text-(--accent)">{String(index + 1).padStart(2, "0")}</div>
                <div>
                  <div className="mb-3 font-mono text-[10px] tracking-[0.12em] text-(--text-subtle)">{sample.tag}</div>
                  <p className="m-0 mb-5 font-serif text-lg font-light leading-6 tracking-[-0.01em] text-(--text)">{sample.q}</p>
                  <div className="flex items-center justify-between border-t border-(--line-soft) pt-4">
                    <span className="text-xs text-(--text-subtle)">Grounded in the Act</span>
                    <span className="font-mono text-[10px] tracking-[0.1em] text-(--accent)">OPEN →</span>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </section>

        <section id="faq" className="py-16 lg:py-20">
          <div className="landing-grid-section mb-10 grid items-baseline gap-6">
            <span className="font-mono text-xs tracking-[0.12em] text-(--accent)">02 / METHOD</span>
            <h2 className="m-0 font-serif text-4xl font-light leading-[1.08] tracking-[-0.02em] text-(--text)">Questions, answered.</h2>
          </div>

          <div className="overflow-hidden rounded-xl border border-(--line) bg-(--surface)">
            {FAQS.map((faq, index) => {
              const isOpen = openFaq === index;
              return (
                <div key={faq.q} className="border-b border-(--line-soft) last:border-b-0">
                  <button
                    type="button"
                    aria-expanded={isOpen}
                    onClick={() => setOpenFaq(isOpen ? -1 : index)}
                    className="landing-grid-faq-q grid w-full items-center gap-4 px-5 py-4 text-left transition-colors duration-200 hover:bg-(--accent-tint)"
                  >
                    <span className="font-mono text-xs tracking-[0.12em] text-(--accent)">{String(index + 1).padStart(2, "0")}</span>
                    <span className="font-serif text-lg font-light tracking-[-0.01em] text-(--text)">{faq.q}</span>
                    <span className="text-right font-serif text-xl font-light text-(--text-subtle)" aria-hidden="true">{isOpen ? "−" : "+"}</span>
                  </button>
                  {isOpen && (
                    <div className="landing-grid-faq-q grid gap-4 px-5 pb-4">
                      <div className="col-start-2 max-w-[64ch] text-sm leading-6 text-(--text-muted)">{faq.a}</div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      </main>

      <footer className="grid grid-cols-1 items-center gap-6 border-t border-(--line) py-8 sm:grid-cols-[1fr_auto]">
        <div className="flex flex-wrap items-center gap-6">
          <div className="flex items-center gap-3">
            <CompassMark ticks={false} />
            <span className="text-xs font-semibold tracking-[0.24em] text-(--text)">LOCUS</span>
          </div>
          <span className="font-serif text-sm font-light italic text-(--text-muted)">A research instrument for the Malaysian Bar.</span>
        </div>
        <div className="flex gap-3 font-mono text-xs tracking-[0.12em] text-(--text-subtle)">
          <span>KUALA LUMPUR</span>
          <span>·</span>
          <span>MMXXVI</span>
        </div>
      </footer>
    </div>
  );
}
