export const DEFAULT_QUESTION =
  "8월 초에 부모님 모시고 부산 해운대 가는데 주의할 게 있을까?";

export const FULL_ANSWER = `부산 해운대구는 8월 초에 폭염, 호우, 태풍 위험이 동시에 높아지는 지역입니다. 고령자와 함께 이동한다면 아래 사항을 먼저 확인하세요.

**폭염 대비**
- 오전 11시부터 오후 3시 사이에는 백사장 활동을 줄이세요.
- 30분마다 물을 마시고, 그늘이나 실내 냉방 공간에서 쉬세요.
- 이동은 오전 8~10시 또는 오후 5시 이후로 계획하세요.

**호우·태풍 행동요령**
- 강수량이 빠르게 늘면 해안 저지대, 지하차도, 하천변 접근을 피하세요.
- 숙소 주변 대피 경로와 가장 가까운 실내 대피 장소를 미리 확인하세요.
- 태풍 예보가 있으면 해안가 산책과 야외 일정을 실내 일정으로 바꾸세요.

**종합 권고**
기상청과 해운대구청 재난문자를 확인하고, 긴급 상황에서는 119 또는 해운대구 보건소 연락처를 이용하세요.`;

export const RISK_DATA = [
  { name: "폭염", score: 88, color: "#f97316", icon: "heat" },
  { name: "호우", score: 72, color: "#3b82f6", icon: "rain" },
  { name: "태풍", score: 61, color: "#8b5cf6", icon: "wind" },
] as const;

export const TRACE_EVENTS = [
  { label: "parsed", value: "부산 해운대구 · 8월 · 고령자 동반" },
  { label: "stats", value: "위험도 계산 완료" },
  { label: "token", value: "응답 스트리밍 완료" },
  { label: "citation", value: "공식 행동요령 2건 인용" },
  { label: "done", value: "Mock scenario passed" },
] as const;

export const PARSED_CARDS = [
  { icon: "map", label: "지역", value: "부산 해운대구" },
  { icon: "calendar", label: "시기", value: "8월 초" },
  { icon: "users", label: "동반자", value: "고령자(부모님)" },
] as const;

export const CITATIONS = [
  "GUIDE-HEAT-ELDERLY-001",
  "GUIDE-RAIN-FLOOD-002",
] as const;

