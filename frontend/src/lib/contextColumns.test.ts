import { describe, expect, it } from "vitest";
import {
  availableContextColumns,
  previewColumnValues,
} from "./contextColumns";

describe("context column helpers", () => {
  it("excludes source and target without fixed names", () => {
    expect(
      availableContextColumns(
        ["ข้อความ", "ผู้พูด", "scene", "คำแปล"],
        "ข้อความ",
        "คำแปล",
      ),
    ).toEqual(["ผู้พูด", "scene"]);
  });

  it("returns compact non-empty deduplicated examples", () => {
    expect(
      previewColumnValues(
        [
          { speaker: " Karen " },
          { speaker: "" },
          { speaker: "Karen" },
          { speaker: "ริค" },
          { speaker: "42" },
        ],
        "speaker",
      ),
    ).toEqual(["Karen", "ริค", "42"]);
  });
});
