import { visit } from "unist-util-visit";
import type { Element, ElementContent, Root, Text } from "hast";
import type { Citation } from "@/lib/useQuery";
import { formatSourceTitle } from "./citationRefs";

// Never linkify inside these — links can't nest, and code should stay verbatim.
const SKIP_PARENTS = new Set(["a", "code", "pre"]);

// "Section 12", "s. 12A", "§ 12(1)(b)", "sections 4 and 5"…
const SECTION_PATTERN = "(?:§\\s*|(?:sections?|secs?|ss?)\\.?\\s+)(\\d+[A-Za-z]?(?:\\([0-9A-Za-z]+\\))*)";

type Lookups = {
  matcher: RegExp;
  sectionToRef: Map<string, Citation>;
  actToRef: Map<string, Citation>;
  hasActs: boolean;
};

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// A citation's section can be "12", "12A", "12(1)" — reduce to the base number so
// "section 12(1)" in prose still resolves to the citation for section 12.
function sectionKey(section: string) {
  return section.replace(/\s/g, "").replace(/\(.*$/, "").toLowerCase();
}

function buildLookups(citations: Citation[]): Lookups {
  const sectionToRef = new Map<string, Citation>();
  const actToRef = new Map<string, Citation>();

  citations.forEach((citation) => {
    if (!citation.pdf_url) return;

    const secKey = sectionKey(citation.section_number ?? "");
    if (secKey && !sectionToRef.has(secKey)) sectionToRef.set(secKey, citation);

    const actKey = formatSourceTitle(citation.act_title ?? "").toLowerCase();
    if (actKey && !actToRef.has(actKey)) actToRef.set(actKey, citation);
  });

  // Longest act titles first so alternation is greedy about the fullest match.
  const actAlternation = [...actToRef.keys()]
    .sort((a, b) => b.length - a.length)
    .map(escapeRegExp)
    .join("|");

  const parts = [SECTION_PATTERN];
  if (actAlternation) parts.push(`(${actAlternation})`);

  return {
    matcher: new RegExp(parts.join("|"), "gi"),
    sectionToRef,
    actToRef,
    hasActs: actAlternation.length > 0,
  };
}

function citationAnchor(citation: Citation, value: string): Element {
  const href = citation.page_number ? `${citation.pdf_url}#page=${citation.page_number}` : citation.pdf_url;

  return {
    type: "element",
    tagName: "a",
    properties: {
      href,
      className: ["chamber-cite"],
      title: `Open ${formatSourceTitle(citation.act_title ?? "")} ↗`,
      target: "_blank",
      rel: "noopener noreferrer",
    },
    children: [{ type: "text", value }],
  };
}

function linkifyValue(value: string, lookups: Lookups): ElementContent[] | null {
  const { matcher, sectionToRef, actToRef } = lookups;
  matcher.lastIndex = 0;

  const out: ElementContent[] = [];
  let lastIndex = 0;
  let matched = false;
  let match: RegExpExecArray | null;

  while ((match = matcher.exec(value)) !== null) {
    // Guard against zero-length matches locking the loop.
    if (match.index === matcher.lastIndex) matcher.lastIndex += 1;

    const full = match[0];
    const sectionNumber = match[1];
    const actTitle = match[2];

    const citation = sectionNumber
      ? sectionToRef.get(sectionKey(sectionNumber))
      : actTitle
        ? actToRef.get(actTitle.toLowerCase())
        : undefined;

    // Only linkify when we actually have a source to point at.
    if (!citation) continue;

    if (match.index > lastIndex) {
      out.push({ type: "text", value: value.slice(lastIndex, match.index) });
    }
    out.push(citationAnchor(citation, full));
    lastIndex = match.index + full.length;
    matched = true;
  }

  if (!matched) return null;

  if (lastIndex < value.length) {
    out.push({ type: "text", value: value.slice(lastIndex) });
  }

  return out;
}

/**
 * rehype plugin: turns in-prose mentions of a cited section ("Section 12(1)") or
 * act title ("Employment Act 1955") into anchors that open that source's PDF directly.
 */
export function rehypeCitationLinks(options: { citations: Citation[] }) {
  const { citations } = options;

  return (tree: Root) => {
    if (!citations || citations.length === 0) return;
    const lookups = buildLookups(citations);

    visit(tree, "text", (node: Text, index, parent) => {
      if (parent == null || index == null) return;
      if (parent.type === "element" && SKIP_PARENTS.has((parent as Element).tagName)) return;

      const replacement = linkifyValue(node.value, lookups);
      if (!replacement) return;

      (parent as Element).children.splice(index, 1, ...replacement);
      // Resume past the nodes we just inserted so we don't re-scan anchors.
      return index + replacement.length;
    });
  };
}
