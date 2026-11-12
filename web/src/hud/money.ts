/** Dollars spent, to the cent; a positive amount under a cent shows as "<$0.01", never "$0.00". */
export function formatSpend(usd: number): string {
  if (usd > 0 && usd < 0.01) return "<$0.01";
  return `$${usd.toFixed(2)}`;
}
