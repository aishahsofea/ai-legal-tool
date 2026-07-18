import type { Components } from "react-markdown";

export const markdownComponents: Components = {
  p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-(--text)">{children}</strong>,
  em: ({ children }) => <em className="font-serif italic text-(--accent)">{children}</em>,
  h1: ({ children }) => <h1 className="mb-3 font-serif text-xl font-light leading-7 tracking-tight text-(--text)">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-3 mt-6 font-serif text-lg font-light leading-6 tracking-tight text-(--text)">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-3 mt-5 font-serif text-base font-light leading-6 text-(--text)">{children}</h3>,
  blockquote: ({ children }) => <blockquote className="my-3 rounded-r-lg border-l border-(--accent) bg-(--accent-tint) px-3 py-2 font-serif text-sm italic leading-6 text-(--text-muted)">{children}</blockquote>,
  ol: ({ children }) => <ol className="my-4 list-decimal space-y-2 pl-6">{children}</ol>,
  ul: ({ children }) => <ul className="my-4 list-disc space-y-2 pl-6">{children}</ul>,
  li: ({ children }) => <li className="pl-2">{children}</li>,
  a: ({ children, href, className, title }) => {
    const isInPageAnchor = href?.startsWith("#");
    return (
      <a
        className={className ? `chamber-link ${className}` : "chamber-link"}
        href={href}
        title={title}
        {...(isInPageAnchor ? {} : { target: "_blank", rel: "noopener noreferrer" })}
      >
        {children}
      </a>
    );
  },
  code: ({ children }) => <code className="rounded-lg border border-(--line) bg-(--surface) px-2 py-1 font-mono text-xs text-(--text)">{children}</code>,
  pre: ({ children }) => <pre className="my-3 overflow-x-auto rounded-lg border border-(--line) bg-(--surface) p-3 font-mono text-xs leading-5 text-(--text-muted)">{children}</pre>,
  hr: () => <hr className="my-6 border-(--line-soft)" />,
  table: ({ children }) => <div className="my-3 overflow-x-auto rounded-lg border border-(--line)"><table className="w-full border-collapse text-sm">{children}</table></div>,
  thead: ({ children }) => <thead className="border-b border-(--line) bg-(--surface-soft)">{children}</thead>,
  tbody: ({ children }) => <tbody className="divide-y divide-(--line-soft)">{children}</tbody>,
  tr: ({ children }) => <tr className="text-left">{children}</tr>,
  th: ({ children }) => <th className="px-3 py-2 font-semibold text-(--text)">{children}</th>,
  td: ({ children }) => <td className="px-3 py-2 text-(--text-muted)">{children}</td>,
};
