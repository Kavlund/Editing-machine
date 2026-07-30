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

// Lighten (amt > 0, toward white) or darken (amt < 0, toward black) a hex colour
// by |amt| in [0,1]. Used to build a coherent, on-brand monochrome scheme from the
// client's single accent, so every template has depth without a clashing 2nd colour.
export function shade(hex: string, amt: number): string {
  const m = /^#?([0-9a-fA-F]{6})$/.exec((hex || "").trim());
  if (!m) return hex || "#888888";
  const n = parseInt(m[1], 16);
  let r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  const t = Math.max(-1, Math.min(1, amt));
  const to = t >= 0 ? 255 : 0;
  const k = Math.abs(t);
  r = Math.round(r + (to - r) * k);
  g = Math.round(g + (to - g) * k);
  b = Math.round(b + (to - b) * k);
  const hx = (v: number) => v.toString(16).padStart(2, "0");
  return `#${hx(r)}${hx(g)}${hx(b)}`;
}

// rgba() string from a hex + alpha — for soft panels/tints over video.
export function withAlpha(hex: string, a: number): string {
  const [r, g, b] = hexToRgb01(hex).map((v) => Math.round(v * 255));
  return `rgba(${r},${g},${b},${Math.max(0, Math.min(1, a))})`;
}

// The client's SECOND brand colour when they set one (and it differs), else a deeper
// tone of the primary accent — so a template that wants two tones always stays on brand
// and never clashes. Both colours come from the client profile via the pipeline.
export function secondaryAccent(accent?: string, accent2?: string): string {
  const a = readableAccent(accent);
  if (accent2 && /^#?[0-9a-fA-F]{6}$/.test((accent2 || "").trim())) {
    const s = readableAccent(accent2);
    if (s.toLowerCase() !== a.toLowerCase()) return s;
  }
  return shade(a, -0.28);
}

export function hexToRgb01(hex: string): [number, number, number] {
  const m = /^#?([0-9a-fA-F]{6})$/.exec((hex || "").trim());
  if (!m) return [1, 1, 1];
  const n = parseInt(m[1], 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

// Swap a documented SENTINEL colour (default magenta #ff00ff, the placeholder you
// paint in Jitter) for the brand accent, walking the parsed Lottie JSON. Only static
// fill/stroke colours are touched; keyframed / gradient colours are left alone. If no
// sentinel is found the animation renders in its original palette. Never throws.
export function recolorLottie(json: any, accentHex?: string, sentinelHex = "#ff00ff"): any {
  try {
    const [ar, ag, ab] = hexToRgb01(readableAccent(accentHex));
    const [sr, sg, sb] = hexToRgb01(sentinelHex);
    const tol = 0.04;
    const near = (a: number, b: number) => Math.abs(a - b) < tol;
    const walk = (node: any) => {
      if (Array.isArray(node)) {
        node.forEach(walk);
      } else if (node && typeof node === "object") {
        const k = node.c && node.c.k;
        if (
          Array.isArray(k) && k.length >= 3 && typeof k[0] === "number" &&
          near(k[0], sr) && near(k[1], sg) && near(k[2], sb)
        ) {
          k[0] = ar; k[1] = ag; k[2] = ab;
        }
        Object.keys(node).forEach((key) => walk(node[key]));
      }
    };
    walk(json);
  } catch (e) {
    /* leave original colours on any error */
  }
  return json;
}
