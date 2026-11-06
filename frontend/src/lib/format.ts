/** "just now", "5 min ago", "3 h ago", "2 d ago", else a short date. */
export function timeAgo(iso: string, now: number): string {
  if (!now) return new Date(iso).toLocaleString("en", { dateStyle: "medium", timeStyle: "short" });
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 7 * 86400) return `${Math.round(s / 86400)} d ago`;
  return new Date(iso).toLocaleDateString("en", { month: "short", day: "numeric" });
}

export function usd(value: number, digits = 4): string {
  return `$${value.toFixed(digits)}`;
}
