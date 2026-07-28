import { cancelRender, continueRender, delayRender, staticFile } from "remotion";

// Shared, self-contained brand font. Loaded once (ES module singleton) BEFORE any
// frame is captured, so headless Chromium never renders a fallback typeface and
// there is no runtime font fetch. Every template imports FONT_FAMILY from here.
export const FONT_FAMILY = "BrandOswald";

const handle = delayRender("loading brand font");
const face = new FontFace(FONT_FAMILY, `url(${staticFile("Oswald.ttf")})`, {
  weight: "700",
});
face
  .load()
  .then((loaded) => {
    (document.fonts as FontFaceSet).add(loaded);
    continueRender(handle);
  })
  .catch((e) => cancelRender(e));
