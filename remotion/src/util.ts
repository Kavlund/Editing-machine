// Keep brand colour when it's bright enough to read, but rescue a dark brand
// accent so text/decoration never disappears over video. A client whose accent
// is a deep green or navy would otherwise render unreadable graphics.
export function readableAccent(hex?: string): string {
  const c = (hex || "#ffffff").trim();
  const m = /^#?([0-9a-fA-F]{6})$/.exec(c);
  if (!m) return "#8ab4ff"; // safe bright fallback for a malformed value
  const n = parseInt(m[1], 16);
  let r = (n >> 16) & 255,
    g = (n >> 8) & 255,
    b = n & 255;
  const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  if (lum >= 0.5) return "#" + m[1].toLowerCase(); // already legible
  // Blend toward white until it reads on a dark panel over video.
  const t = 0.55;
  r = Math.round(r + (255 - r) * t);
  g = Math.round(g + (255 - g) * t);
  b = Math.round(b + (255 - b) * t);
  const hx = (v: number) => v.toString(16).padStart(2, "0");
  return `#${hx(r)}${hx(g)}${hx(b)}`;
}
