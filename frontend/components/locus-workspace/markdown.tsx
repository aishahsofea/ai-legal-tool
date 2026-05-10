import type { Components } from "react-markdown";

export const markdownComponents: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-(--ink)">{children}</strong>,
  em: ({ children }) => <em className="font-serif italic text-(--bronze)">{children}</em>,
  h1: ({ children }) => <h1 className="mb-2 font-serif text-2xl font-light leading-tight tracking-tight text-(--ink)">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-2 mt-4 font-serif text-xl font-light leading-tight tracking-tight text-(--ink)">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-2 mt-4 font-serif text-base font-light leading-snug text-(--ink)">{children}</h3>,
  blockquote: ({ children }) => <blockquote className="my-2 border-l border-(--bronze) pl-4 font-serif text-sm italic leading-relaxed text-(--ink-2)">{children}</blockquote>,
  ol: ({ children }) => <ol className="my-2 list-decimal space-y-2 pl-4">{children}</ol>,
  ul: ({ children }) => <ul className="my-2 list-disc space-y-2 pl-4">{children}</ul>,
  li: ({ children }) => <li className="pl-2">{children}</li>,
  a: ({ children, href }) => <a className="chamber-link" href={href}>{children}</a>,
  code: ({ children }) => <code className="rounded-sm border border-(--rule) bg-(--bg-2) px-2 py-2 font-mono text-xs text-(--ink)">{children}</code>,
  pre: ({ children }) => <pre className="my-2 overflow-x-auto rounded-sm border border-(--rule) bg-(--bg-2) p-2 font-mono text-xs leading-relaxed text-(--ink-2)">{children}</pre>,
  hr: () => <hr className="my-4 border-(--rule-soft)" />,
  table: ({ children }) => <div className="my-2 overflow-x-auto"><table className="w-full border-collapse text-sm">{children}</table></div>,
  thead: ({ children }) => <thead className="border-b border-(--rule)">{children}</thead>,
  tbody: ({ children }) => <tbody className="divide-y divide-(--rule-soft)">{children}</tbody>,
  tr: ({ children }) => <tr className="text-left">{children}</tr>,
  th: ({ children }) => <th className="px-3 py-2 font-semibold text-(--ink)">{children}</th>,
  td: ({ children }) => <td className="px-3 py-2 text-(--ink-2)">{children}</td>,
};
