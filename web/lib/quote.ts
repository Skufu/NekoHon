/** Quote matching, shared by the reader's highlight and the answer parser.
 *  Pure functions: a regex for a verbatim quote, whitespace-insensitive. */

export function escapeRegExp(text: string) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function quotePattern(quote: string) {
  const words = quote.trim().split(/\s+/).map(escapeRegExp);
  return new RegExp(words.join("\\s+"));
}
