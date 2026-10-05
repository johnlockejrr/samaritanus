import { renderToString } from "react-dom/server";
import { createElement } from "react";
import { describe, it, expect } from "vitest";
import Highlight, { markTokens, parseHighlight } from "../src/Highlight.jsx";

const HLO = "<" + "hl>";
const HLC = "</" + "hl>";

describe("parseHighlight", () => {
  it("returns a single non-hit part when nothing is marked", () => {
    expect(parseHighlight(undefined, "שלום")).toEqual([
      { text: "שלום", hit: false },
    ]);
  });

  it("splits marked segments with hit flags", () => {
    expect(parseHighlight(HLO + "א" + HLC + "להים")).toEqual([
      { text: "א", hit: true },
      { text: "להים", hit: false },
    ]);
  });

  it("handles a leading mark and an unterminated mark", () => {
    expect(parseHighlight("x" + HLO + "y")).toEqual([
      { text: "x", hit: false },
      { text: "y", hit: true },
    ]);
  });

  it("treats markup in the plain text as text, never as structure", () => {
    const evil = "<" + "script>bad</" + "script>";
    const parts = parseHighlight(undefined, evil);
    expect(parts.length).toBe(1);
    expect(parts[0].hit).toBe(false);
    expect(parts[0].text).toBe(evil);
  });
});

describe("markTokens", () => {
  it("bolds the inflected form and leaves lookalikes alone", () => {
    const parts = markTokens("ויברא אלהים וברית", ["ויברא"]);
    expect(parts.filter((part) => part.hit).map((part) => part.text)).toEqual(["ויברא"]);
  });

  it("matches a vocalized query form against consonantal text", () => {
    const parts = markTokens("בראשית ברא אלהים", ["בָּרָ֣א"]);
    expect(parts.filter((part) => part.hit).map((part) => part.text)).toEqual(["ברא"]);
  });
});

describe("Highlight component", () => {
  it("renders real <strong> nodes for hits", () => {
    const html = renderToString(
      createElement(Highlight, {
        marked: "x" + HLO + "א" + HLC + "y",
        plain: "",
      }),
    );
    expect(html).toContain("x");
    expect(html).toContain("<strong");
    expect(html).toContain("א");
    expect(html).toContain("y");
  });

  it("escapes injected markup in plain text (no raw HTML)", () => {
    const evil = "<" + "img src=x onerror=alert(1)>";
    const html = renderToString(createElement(Highlight, { plain: evil }));
    expect(html).not.toContain("<" + "img");
    expect(html).toContain("&lt;");
  });
});
