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
