import type { Components } from "react-markdown";

export const markdownComponents: Components = {
  p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-(--ink)">{children}</strong>,
  em: ({ children }) => <em className="font-serif italic text-(--bronze)">{children}</em>,
  h1: ({ children }) => <h1 className="mb-4 font-serif text-3xl font-light leading-tight tracking-tight text-(--ink)">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-3 mt-6 font-serif text-2xl font-light leading-tight tracking-tight text-(--ink)">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-2 mt-5 font-serif text-lg font-light leading-snug text-(--ink)">{children}</h3>,
  blockquote: ({ children }) => <blockquote className="my-4 border-l border-(--bronze) pl-4 font-serif text-base italic leading-relaxed text-(--ink-2)">{children}</blockquote>,
  ol: ({ children }) => <ol className="my-3 list-decimal space-y-3 pl-5">{children}</ol>,
  ul: ({ children }) => <ul className="my-3 list-disc space-y-3 pl-5">{children}</ul>,
  li: ({ children }) => <li className="pl-1">{children}</li>,
  a: ({ children, href }) => <a className="chamber-link" href={href}>{children}</a>,
  code: ({ children }) => <code className="rounded-sm border border-(--rule) bg-(--bg-2) px-1 py-0.5 font-mono text-sm text-(--ink)">{children}</code>,
  pre: ({ children }) => <pre className="my-4 overflow-x-auto rounded-sm border border-(--rule) bg-(--bg-2) p-4 font-mono text-sm leading-relaxed text-(--ink-2)">{children}</pre>,
  hr: () => <hr className="my-5 border-(--rule-soft)" />,
};
