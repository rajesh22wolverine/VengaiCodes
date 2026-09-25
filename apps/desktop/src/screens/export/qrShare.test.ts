import QRCode from "qrcode";
import { describe, expect, it } from "vitest";

import {
  classifyQrText,
  clampFps,
  decodeQrPixels,
  loopDuration,
  qrFileName,
  reachWarning,
} from "./qrShare";

const BASE45 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:";

/** Renders a code the way the apps draw it (the `qrcode` library), as
 *  RGBA pixels a real decoder can read. */
function renderPixels(text: string, scale = 4) {
  const qr = QRCode.create(text, { errorCorrectionLevel: "M" });
  const size = qr.modules.size;
  const border = 4;
  const width = (size + border * 2) * scale;
  const data = new Uint8ClampedArray(width * width * 4).fill(255);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if (!qr.modules.data[y * size + x]) continue;
      for (let dy = 0; dy < scale; dy++) {
        for (let dx = 0; dx < scale; dx++) {
          const i = (((y + border) * scale + dy) * width + (x + border) * scale + dx) * 4;
          data[i] = data[i + 1] = data[i + 2] = 0;
        }
      }
    }
  }
  return { data, width };
}

function seeded(seed: number) {
  let s = seed;
  return () => {
    s = (s * 1103515245 + 12345) % 2 ** 31;
    return s / 2 ** 31;
  };
}

describe("sequence frames drawn with `qrcode` decode back exactly", () => {
  // Frames look like the backend's: "VGS1:<SID>:<i>:<n>:" + base45 data,
  // which includes spaces, %, :, / etc. — every one must survive.
  const rand = seeded(42);
  const frames = [300, 500, 800].map((bytes, i) => {
    const chars = Math.ceil((bytes * 3) / 2);
    const data = Array.from({ length: chars }, () => BASE45[Math.floor(rand() * 45)]).join("");
    return `VGS1:1A2B3C4D:${i}:3:${data}`;
  });

  it.each(frames.map((f) => [f.length, f]))("a %i-character frame", (_len, frame) => {
    const { data, width } = renderPixels(frame as string);
    expect(decodeQrPixels(data, width, width)).toBe(frame);
  });

  it("a download link", () => {
    const url = "https://api.example.com/api/v1/share/d/3_ZkdVT_w6iQePrWYEVEkGX3";
    const { data, width } = renderPixels(url);
    expect(decodeQrPixels(data, width, width)).toBe(url);
  });

  it("finds nothing in a blank image", () => {
    const blank = new Uint8ClampedArray(200 * 200 * 4).fill(255);
    expect(decodeQrPixels(blank, 200, 200)).toBeNull();
  });
});

describe("helpers", () => {
  it("classifies scanned text", () => {
    expect(classifyQrText(" https://x.io/a ")).toBe("link");
    expect(classifyQrText("VGC1:ABC")).toBe("blueprint");
    expect(classifyQrText("VGS1:1A2B3C4D:0:3:AB")).toBe("sequence");
    expect(classifyQrText("hello")).toBe("unknown");
  });

  it("warns only when a link can't reach other devices", () => {
    expect(reachWarning("anyone")).toBeNull();
    expect(reachWarning("this_device")).toMatch(/localhost/);
    expect(reachWarning("same_network")).toMatch(/same Wi-Fi/);
  });

  it("names and times things", () => {
    expect(qrFileName("Café Orders!", "blueprint")).toBe("Caf_Orders_blueprint_qr.png");
    expect(loopDuration(26, 4)).toBe("about 7 s");
    expect(loopDuration(600, 2)).toBe("about 5 min");
    expect(clampFps(0)).toBe(1);
    expect(clampFps(20)).toBe(8);
  });
});
