import { describe, expect, it } from "vitest";
import { cost, duration, nodeLabel, percent, tokens } from "./format";

describe("duration", () => {
  it("renders sub-second, second and minute scales", () => {
    expect(duration(450)).toBe("450 ms");
    expect(duration(1500)).toBe("1.5 s");
    expect(duration(95_000)).toBe("1m 35s");
  });

  it("renders an em dash rather than '0 ms' when there is no measurement", () => {
    expect(duration(0)).toBe("—");
  });
});

describe("cost", () => {
  it("keeps four decimals so sub-cent runs are still visible", () => {
    expect(cost(0.0372)).toBe("$0.0372");
    expect(cost(0)).toBe("$0.0000");
  });
});

describe("percent", () => {
  it("formats rates", () => {
    expect(percent(0.833)).toBe("83.3%");
    expect(percent(1, 0)).toBe("100%");
  });
});

describe("tokens", () => {
  it("abbreviates thousands", () => {
    expect(tokens(940)).toBe("940");
    expect(tokens(6200)).toBe("6.2k");
  });
});

describe("nodeLabel", () => {
  it("maps graph node names to human labels", () => {
    expect(nodeLabel("form_hypothesis")).toBe("Root-cause hypothesis formed");
    expect(nodeLabel("review_solution")).toBe("Reviewer verification");
  });

  it("falls back to a readable form for unknown nodes", () => {
    expect(nodeLabel("some_new_node")).toBe("some new node");
  });
});
