import { strFromU8, unzipSync } from "fflate";
import { describe, expect, it } from "vitest";

import fixture from "./__fixtures__/qrSequence.json";
import {
  SequenceCollector,
  base45Decode,
  base64ToBytes,
  buildZip,
  classifyScan,
  crc32,
  decodeBundle,
  parseFrame,
  qrModules,
  qrPath,
  safeZipPath,
  zipFileName,
} from "./qrTransfer";

// The fixture's frames were made by the REAL backend
// (services/qr_share.build_sequence) from its `files` — so these tests pin
// the phone to the server's actual format, not to a copy of it.

describe("base45Decode (RFC 9285)", () => {
  const vectors: [string, string][] = [
    ["BB8", "AB"],
    ["%69 VD92EX0", "Hello!!"],
    ["UJCLQE7W581", "base-45"],
    ["QED8WEX0", "ietf!"],
  ];
  it.each(vectors)("%s -> %s", (encoded, raw) => {
    expect(strFromU8(base45Decode(encoded))).toBe(raw);
  });

  it("refuses text that isn't base45", () => {
    expect(() => base45Decode("abc")).toThrow();
    expect(() => base45Decode("GGW")).toThrow(); // a group over 65535
    expect(() => base45Decode("A")).toThrow();
  });
});

describe("crc32", () => {
  it("matches the standard check value", () => {
    expect(crc32(new TextEncoder().encode("123456789"))).toBe(0xcbf43926);
  });
});

describe("classifyScan", () => {
  it("tells the three kinds of code apart", () => {
    expect(classifyScan("https://api.example.com/api/v1/share/d/abc")).toBe("link");
    expect(classifyScan("VGC1:ABC")).toBe("blueprint");
    expect(classifyScan(fixture.frames[0])).toBe("sequence");
    expect(classifyScan("hello")).toBe("unknown");
  });
});

describe("parseFrame", () => {
  it("reads a backend frame", () => {
    const frame = parseFrame(fixture.frames[0])!;
    expect(frame.sid).toBe(fixture.sid);
    expect([frame.index, frame.count]).toEqual([0, fixture.frames.length]);
    expect(frame.data.length).toBe(200);
  });

  it("rejects anything malformed", () => {
    expect(parseFrame("VGS1:XYZ:0:3:AAA")).toBeNull();
    expect(parseFrame(`VGS1:${fixture.sid}:5:3:AAA`)).toBeNull();
    expect(parseFrame(`VGS1:${fixture.sid}:0:3:abc`)).toBeNull();
    expect(parseFrame("VGC1:ABC")).toBeNull();
  });
});

describe("SequenceCollector", () => {
  it("rebuilds the backend's files from frames scanned in any order", () => {
    const c = new SequenceCollector();
    const order = [...fixture.frames].reverse();
    order.forEach((f) => expect(c.add(f).accepted).toBe(true));
    expect(c.add(fixture.frames[2])).toEqual({ accepted: true, isNew: false, otherTransfer: false });
    expect(c.complete).toBe(true);

    const bundle = decodeBundle(c.assemble());
    expect(bundle.name).toBe(fixture.name);
    expect(bundle.files).toEqual(fixture.files);
  });

  it("knows what's missing and won't assemble early", () => {
    const c = new SequenceCollector();
    fixture.frames.slice(0, -2).forEach((f) => c.add(f));
    expect(c.missing()).toEqual([fixture.frames.length - 2, fixture.frames.length - 1]);
    expect(() => c.assemble()).toThrow(/Still missing 2/);
  });

  it("flags a frame from another transfer instead of mixing it in", () => {
    const c = new SequenceCollector();
    c.add(fixture.frames[0]);
    const other = fixture.frames[1].replace(`:${fixture.frames.length}:`, `:${fixture.frames.length + 1}:`);
    expect(c.add(other)).toEqual({ accepted: false, isNew: false, otherTransfer: true });
  });

  it("detects corrupted data", () => {
    const c = new SequenceCollector();
    const frames = [...fixture.frames];
    const cut = frames[0].lastIndexOf(":") + 1;
    frames[0] = frames[0].slice(0, cut) + (frames[0][cut] === "0" ? "1" : "0") + frames[0].slice(cut + 1);
    frames.forEach((f) => c.add(f));
    expect(() => c.assemble()).toThrow(/didn't check out/);
  });
});

describe("buildZip", () => {
  it("makes the same ZIP contents Download ZIP would", () => {
    const zip = unzipSync(buildZip(fixture.files as [string, string][]));
    expect(Object.keys(zip)).toEqual(fixture.files.map(([p]) => p));
    expect(strFromU8(zip["README.md"])).toBe(fixture.files[0][1]);
    expect(zip["frontend/src/empty.js"].length).toBe(0);
  });

  it("keeps every path inside the ZIP", () => {
    expect(safeZipPath("/../etc/passwd")).toBe("etc/passwd");
    expect(safeZipPath("a/../../b\\..\\c/./d")).toBe("a/b/c/d");
    expect(safeZipPath("backend/models/order.py")).toBe("backend/models/order.py");
    const zip = unzipSync(buildZip([["/../etc/passwd", "x"]]));
    expect(Object.keys(zip)).toEqual(["etc/passwd"]);
  });

  it("names the file after the project", () => {
    expect(zipFileName("Café Orders!")).toBe("Caf_Orders.zip");
    expect(zipFileName("  ")).toBe("vengaicode_project.zip");
  });
});

describe("qrModules", () => {
  it("draws a frame as a real QR matrix", () => {
    const modules = qrModules(fixture.frames[0]);
    expect(modules.length).toBeGreaterThan(21);
    expect(modules.every((row) => row.length === modules.length)).toBe(true);
    // Finder pattern: the top-left 7x7 has a solid dark border.
    expect(modules[0].slice(0, 7).every(Boolean)).toBe(true);
    expect(qrPath(modules).startsWith("M0 0h1v1h-1z")).toBe(true);
  });
});

describe("base64ToBytes", () => {
  it("decodes with and without padding", () => {
    expect(strFromU8(base64ToBytes("aGVsbG8="))).toBe("hello");
    expect(strFromU8(base64ToBytes("aGVsbG8gd29ybGQ"))).toBe("hello world");
    expect([...base64ToBytes("iVBORw0KGgo=")]).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  });
});
