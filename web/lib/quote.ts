/** Quote matching, shared by the reader's highlight and the answer parser.
 *  Pure functions: a regex for a verbatim quote, whitespace-insensitive. */

function escapeRegExp(text: string) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function quotePattern(quote: string) {
  const rawWords = quote.trim().split(/\s+/);
  const wordPatterns = rawWords.map((w) => {
    const stripped = w.replace(/^["'“”‘’]+|["'“”‘’]+$/g, "");
    const escaped = escapeRegExp(stripped).replace(/[\u2014\u2013-]/g, "[\\u2014\\u2013-]+");
    return `["'“”‘’]?${escaped}\\d*["'“”‘’]?`;
  });
  return new RegExp(wordPatterns.join("[\\s\\u00A0]+"), "i");
}
