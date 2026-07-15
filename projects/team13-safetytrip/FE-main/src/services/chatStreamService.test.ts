import { describe, expect, it } from "vitest";

import { buildApiUrl } from "./apiClient";
import { parseSseChunk } from "./sseParser";

describe("apiClient", () => {
  it("builds API paths with a leading slash", () => {
    expect(buildApiUrl("chat/stream")).toMatch(/\/chat\/stream$/);
  });
});

describe("parseSseChunk", () => {
  it("parses legacy data-only SSE events", () => {
    const events = parseSseChunk(
      [
        'data: {"type":"thinking","status":"stats"}',
        "",
        'data: {"type":"token","content":"hello"}',
        "",
      ].join("\n"),
    );

    expect(events).toEqual([
      { type: "thinking", status: "stats" },
      { type: "token", content: "hello" },
    ]);
  });

  it("parses the normal backend stream flow", () => {
    const events = parseSseChunk(
      [
        "event: session",
        'data: {"thread_id":"17390ba2-3955-45a5-a2f9-773293713f1e"}',
        "",
        "event: parsed",
        'data: {"region":"부산광역시 해운대구","month":"8월","companions":"노약자 동반","intent":"prevention","disaster_type":null}',
        "",
        "event: stats",
        'data: {"scope_used":"sigungu","total_count":132,"risk_scores":[{"disaster_type":"폭염","risk_score":80,"count":56}],"top_risk":"폭염","fallback_notice":null}',
        "",
        "event: citation",
        'data: {"ids":["GUIDE-HEAT-GENERAL-001"]}',
        "",
        "event: token",
        'data: {"text":"해운"}',
        "",
        "event: done",
        "data: {}",
        "",
      ].join("\n"),
    );

    expect(events).toEqual([
      {
        type: "session",
        status: "대화 세션을 연결했습니다.",
        data: { thread_id: "17390ba2-3955-45a5-a2f9-773293713f1e" },
      },
      {
        type: "parsed",
        status: "질문에서 지역과 시기를 분석했습니다.",
        data: {
          region: "부산광역시 해운대구",
          month: "8월",
          companions: "노약자 동반",
          intent: "prevention",
          disaster_type: null,
        },
      },
      {
        type: "stats",
        status: "재난 통계를 계산했습니다.",
        data: {
          scope_used: "sigungu",
          total_count: 132,
          risk_scores: [{ disaster_type: "폭염", risk_score: 80, count: 56 }],
          top_risk: "폭염",
          fallback_notice: null,
        },
      },
      {
        type: "citation",
        status: "공식 행동요령 출처를 확인했습니다.",
        data: { ids: ["GUIDE-HEAT-GENERAL-001"] },
      },
      { type: "token", content: "해운" },
      { type: "done" },
    ]);
  });

  it("parses reask, escalate, degraded, and error events", () => {
    const events = parseSseChunk(
      [
        "event: reask",
        'data: {"message":"지역과 시기를 조금 더 구체적으로 말씀해 주세요."}',
        "",
        "event: escalate",
        'data: {"reason":"관련도 낮음","contact":{"agency":"정부민원 통합콜센터","phone":"110"},"message":"공식 매뉴얼에서 충분한 근거를 찾지 못했습니다."}',
        "",
        "event: degraded",
        'data: {"reason":"AI 답변 생성 실패","contact":{"agency":"소방","phone":"119"}}',
        "",
        "event: error",
        'data: {"message":"일시적으로 AI 서비스에 연결할 수 없습니다."}',
        "",
        "event: unknown_future_event",
        'data: {"message":"ignored"}',
        "",
      ].join("\n"),
    );

    expect(events).toEqual([
      {
        type: "reask",
        content: "지역과 시기를 조금 더 구체적으로 말씀해 주세요.",
        data: { message: "지역과 시기를 조금 더 구체적으로 말씀해 주세요." },
      },
      {
        type: "escalate",
        content: "공식 매뉴얼에서 충분한 근거를 찾지 못했습니다.\n\n문의 기관: 정부민원 통합콜센터 (110)",
        status: "관련도 낮음",
        data: {
          reason: "관련도 낮음",
          contact: { agency: "정부민원 통합콜센터", phone: "110" },
          message: "공식 매뉴얼에서 충분한 근거를 찾지 못했습니다.",
        },
      },
      {
        type: "degraded",
        content: "AI 답변 생성 실패\n\n문의 기관: 소방 (119)",
        status: "AI 답변 생성 실패",
        data: {
          reason: "AI 답변 생성 실패",
          contact: { agency: "소방", phone: "119" },
        },
      },
      {
        type: "error",
        content: "일시적으로 AI 서비스에 연결할 수 없습니다.",
        data: { message: "일시적으로 AI 서비스에 연결할 수 없습니다." },
      },
    ]);
  });

  it("parses degraded followed by token text", () => {
    const events = parseSseChunk(
      [
        "event: degraded",
        'data: {"reason":"AI 답변 생성 실패","contact":{"agency":"소방","phone":"119"}}',
        "",
        "event: token",
        'data: {"text":"공식 행동요령 원문 안내입니다."}',
        "",
        "event: done",
        "data: {}",
        "",
      ].join("\n"),
    );

    expect(events).toEqual([
      {
        type: "degraded",
        content: "AI 답변 생성 실패\n\n문의 기관: 소방 (119)",
        status: "AI 답변 생성 실패",
        data: {
          reason: "AI 답변 생성 실패",
          contact: { agency: "소방", phone: "119" },
        },
      },
      { type: "token", content: "공식 행동요령 원문 안내입니다." },
      { type: "done" },
    ]);
  });
});
