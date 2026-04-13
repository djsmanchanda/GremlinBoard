export function cn(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function formatFreshness(value?: string | null) {
  if (!value) {
    return "No refresh yet";
  }

  const delta = Date.now() - new Date(value).getTime();
  const seconds = Math.max(Math.round(delta / 1000), 0);
  if (seconds < 60) {
    return `${seconds}s ago`;
  }
  if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m ago`;
  }
  return `${Math.round(seconds / 3600)}h ago`;
}
