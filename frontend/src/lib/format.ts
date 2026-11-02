/** "MM:SS" hoặc "HH:MM:SS" sang mili giây. */
export function stampToMs(stamp: string): number | null {
  const parts = stamp.split(":").map((part) => Number(part));
  if (parts.length < 2 || parts.some((part) => !Number.isFinite(part))) return null;
  return parts.reduce((total, part) => total * 60 + part, 0) * 1000;
}

export function formatMs(ms: number) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}
