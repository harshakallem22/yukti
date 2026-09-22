import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Badge, DemoBanner, Stat } from "./ui";
import { Diff } from "./Diff";

describe("Badge", () => {
  it("renders a readable status", () => {
    render(<Badge value="awaiting_approval" />);
    expect(screen.getByText("awaiting approval")).toBeInTheDocument();
  });
});

describe("DemoBanner", () => {
  it("states plainly that demo runs are not the agent reasoning", () => {
    render(<DemoBanner />);
    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent(/scripted test double/i);
    expect(banner).toHaveTextContent(/not Yukti reasoning/i);
  });
});

describe("Stat", () => {
  it("shows label, value and hint", () => {
    render(<Stat label="Task Success" value="83.3%" hint="hidden tests" />);
    expect(screen.getByText("Task Success")).toBeInTheDocument();
    expect(screen.getByText("83.3%")).toBeInTheDocument();
    expect(screen.getByText("hidden tests")).toBeInTheDocument();
  });
});

describe("Diff", () => {
  it("renders added and removed lines", () => {
    const diff = [
      "diff --git a/app/main.py b/app/main.py",
      "@@ -23,7 +23,10 @@",
      "-        user = service.register(email)",
      "+        try:",
    ].join("\n");
    render(<Diff diff={diff} />);
    // The diff view preserves leading whitespace, so text matching must not normalise it.
    const raw = { normalizer: (text: string) => text };
    expect(screen.getByText("+        try:", raw)).toBeInTheDocument();
    expect(screen.getByText("-        user = service.register(email)", raw)).toBeInTheDocument();
  });

  it("says so when a run produced no changes rather than showing an empty box", () => {
    render(<Diff diff="   " />);
    expect(screen.getByText(/no changes were produced/i)).toBeInTheDocument();
  });
});
