import { describe, expect, it } from "vitest";

import {
  CITATIONS,
  DEFAULT_QUESTION,
  FULL_ANSWER,
  PARSED_CARDS,
  RISK_DATA,
  TRACE_EVENTS,
} from "./safetyTripMock";

describe("safetyTripMock", () => {
  it("provides one complete mock answer scenario", () => {
    expect(DEFAULT_QUESTION.length).toBeGreaterThan(0);
    expect(FULL_ANSWER).toContain("119");
    expect(TRACE_EVENTS.at(-1)).toEqual({
      label: "done",
      value: "Mock scenario passed",
    });
  });

  it("keeps risk scores and parsed cards renderable", () => {
    expect(RISK_DATA).toHaveLength(3);
    expect(RISK_DATA.every((risk) => risk.score >= 0 && risk.score <= 100)).toBe(
      true,
    );
    expect(RISK_DATA.map((risk) => risk.icon)).toEqual([
      "heat",
      "rain",
      "wind",
    ]);

    expect(PARSED_CARDS).toHaveLength(3);
    expect(PARSED_CARDS.every((card) => card.icon && card.label && card.value)).toBe(
      true,
    );
  });

  it("keeps citation ids stable for evidence display", () => {
    expect(CITATIONS).toEqual([
      "GUIDE-HEAT-ELDERLY-001",
      "GUIDE-RAIN-FLOOD-002",
    ]);
  });
});
