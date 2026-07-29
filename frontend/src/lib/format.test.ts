import { describe, expect, it } from "vitest";
import type { Job } from "../api";
import { canOpenView, statusLabel, viewForStatus } from "./format";

const baseJob = {
  id: "job",
  filename: "game.csv",
  status: "running",
} as Job;

describe("workspace stage rules", () => {
  it("derives a safe stage from the persisted job status", () => {
    expect(viewForStatus("uploaded")).toBe("config");
    expect(viewForStatus("awaiting_review")).toBe("glossary");
    expect(viewForStatus("paused")).toBe("translate");
    expect(viewForStatus("completed")).toBe("review");
  });

  it("keeps previous stages accessible while future stages stay locked", () => {
    expect(canOpenView(baseJob, "config")).toBe(true);
    expect(canOpenView(baseJob, "glossary")).toBe(true);
    expect(canOpenView(baseJob, "translate")).toBe(true);
    expect(canOpenView(baseJob, "review")).toBe(false);
  });

  it("uses a readable fallback for unknown statuses", () => {
    expect(statusLabel("custom_state")).toBe("custom_state");
  });
});

