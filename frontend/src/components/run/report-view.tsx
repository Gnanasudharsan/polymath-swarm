import "katex/dist/katex.min.css";

import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkMath from "remark-math";

/** Agents write \( \) and \[ \] as often as $ $; normalise to remark-math's delimiters. */
export function normaliseMath(markdown: string): string {
  return markdown
    .replace(/\\\[([\s\S]*?)\\\]/g, (_m, inner: string) => "$$" + inner + "$$")
    .replace(/\\\(([\s\S]*?)\\\)/g, (_m, inner: string) => "$" + inner + "$");
}

/** Evidence report, with maths rendered by KaTeX. */
export function ReportView({ markdown }: { markdown: string }) {
  return (
    <article className="report max-w-none text-sm leading-relaxed" data-testid="report">
      <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
        {normaliseMath(markdown)}
      </ReactMarkdown>
    </article>
  );
}
