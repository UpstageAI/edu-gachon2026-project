import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  Activity,
  AlertTriangle,
  BookOpen,
  Calendar,
  CheckCircle2,
  CloudRain,
  MapPin,
  Play,
  RotateCcw,
  Shield,
  Thermometer,
  Users,
  Wind,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { streamChatResponse } from "../services/chatStreamService";
import type {
  CitationStreamData,
  ErrorStreamData,
  EscalateStreamData,
  ParsedStreamData,
  ReaskStreamData,
  RiskScore,
  SessionStreamData,
  StatsStreamData,
} from "../types/chat";

const DEFAULT_QUESTION = "";

const riskStyles: Record<string, { color: string; icon: typeof AlertTriangle }> = {
  강풍: { color: "#0f7a6e", icon: Wind },
  태풍: { color: "#8b5cf6", icon: Wind },
  폭염: { color: "#f97316", icon: Thermometer },
  호우: { color: "#3b82f6", icon: CloudRain },
};

const fallbackRisk = { color: "#64748b", icon: AlertTriangle };

type NoticeKind = "info" | "warning" | "error";
type StreamOutcome = "idle" | "stats" | "answer-only" | "no-stats" | "error";

interface NoticeState {
  kind: NoticeKind;
  title: string;
  message: string;
}

function getRiskStyle(disasterType: string) {
  return riskStyles[disasterType] ?? fallbackRisk;
}

function RiskTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;

  return (
    <div className="rounded-lg border border-white/70 bg-white/90 px-3 py-2 text-sm text-[#1a2940] shadow-sm backdrop-blur">
      <span className="font-semibold">{payload[0].payload.name}</span>
      <span className="ml-2" style={{ color: payload[0].color }}>
        {payload[0].value}점
      </span>
    </div>
  );
}

function isObject(data: unknown): data is Record<string, unknown> {
  return typeof data === "object" && data !== null;
}

function isParsedData(data: unknown): data is ParsedStreamData {
  return isObject(data);
}

function isSessionData(data: unknown): data is SessionStreamData {
  return isObject(data);
}

function isStatsData(data: unknown): data is StatsStreamData {
  return isObject(data) && "risk_scores" in data;
}

function isCitationData(data: unknown): data is CitationStreamData {
  return isObject(data) && Array.isArray(data.ids);
}

function isReaskData(data: unknown): data is ReaskStreamData {
  return isObject(data);
}

function isEscalateData(data: unknown): data is EscalateStreamData {
  return isObject(data);
}

function isErrorData(data: unknown): data is ErrorStreamData {
  return isObject(data);
}

function renderAnswer(text: string) {
  const normalizedMarkdown = text.replace(/\*\*\s+([^*\n]+?)\s+\*\*/g, "**$1**");

  return (
    <ReactMarkdown
      components={{
        h1: ({ children }) => <h1 className="mb-3 text-lg font-bold text-[#1a2940]">{children}</h1>,
        h2: ({ children }) => <h2 className="mb-2 mt-4 text-base font-bold text-[#1a2940]">{children}</h2>,
        h3: ({ children }) => <h3 className="mb-2 mt-4 text-sm font-bold text-[#1a2940]">{children}</h3>,
        p: ({ children }) => <p className="mb-2 text-sm leading-relaxed text-[#2c4a6b]">{children}</p>,
        strong: ({ children }) => <strong className="font-bold text-[#16365c]">{children}</strong>,
        ul: ({ children }) => <ul className="mb-3 ml-4 list-disc space-y-1 text-sm text-[#2c4a6b]">{children}</ul>,
        ol: ({ children }) => <ol className="mb-3 ml-4 list-decimal space-y-1 text-sm text-[#2c4a6b]">{children}</ol>,
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
        code: ({ children }) => (
          <code className="rounded bg-sky-50 px-1 py-0.5 text-xs font-semibold text-sky-800">{children}</code>
        ),
      }}
    >
      {normalizedMarkdown}
    </ReactMarkdown>
  );
}

function noticeClassName(kind: NoticeKind) {
  const base = "mb-3 rounded-lg border px-3 py-2 text-xs leading-relaxed";

  if (kind === "error") {
    return `${base} border-red-200 bg-red-50 text-red-800`;
  }

  if (kind === "warning") {
    return `${base} border-amber-200 bg-amber-50 text-amber-800`;
  }

  return `${base} border-sky-200 bg-sky-50 text-sky-800`;
}

export default function App() {
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [ran, setRan] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [displayedAnswer, setDisplayedAnswer] = useState("");
  const [notice, setNotice] = useState<NoticeState | null>(null);
  const [parsed, setParsed] = useState<ParsedStreamData | null>(null);
  const [riskScores, setRiskScores] = useState<RiskScore[]>([]);
  const [statsReceived, setStatsReceived] = useState(false);
  const [streamOutcome, setStreamOutcome] = useState<StreamOutcome>("idle");
  const [threadId, setThreadId] = useState<string | null>(null);
  const [topRisk, setTopRisk] = useState<string | null>(null);
  const [citations, setCitations] = useState<string[]>([]);
  const [traceEvents, setTraceEvents] = useState<{ label: string; value: string }[]>([]);

  const chartData = useMemo(
    () =>
      riskScores.map((risk) => ({
        name: risk.disaster_type,
        score: risk.risk_score,
        count: risk.count,
        color: getRiskStyle(risk.disaster_type).color,
      })),
    [riskScores],
  );

  const parsedCards = [
    { icon: MapPin, label: "지역", value: parsed?.region ?? "-" },
    { icon: Calendar, label: "시기", value: parsed?.month ?? "-" },
    { icon: Users, label: "동반자", value: parsed?.companions ?? "-" },
  ];

  const hasParsedRegion = Boolean(parsed?.region && parsed.region !== "-");
  const hasParsedMonth = Boolean(parsed?.month && parsed.month !== "-");
  const analysisTitle = hasParsedRegion
    ? `${parsed?.region}${hasParsedMonth ? ` ${parsed?.month}` : ""} 안전 분석`
    : "질문 기반 안전 분석";

  const riskEmptyMessage = (() => {
    if (statsReceived) return "해당 조건의 위험 통계가 없습니다.";
    if (streamOutcome === "answer-only") return "이 답변에는 별도 위험도 통계가 없습니다.";
    if (streamOutcome === "no-stats") return "표시할 위험 통계가 없습니다.";
    if (streamOutcome === "error") return "통계를 불러오지 못했습니다.";
    if (ran) return "통계 이벤트를 기다리는 중입니다.";
    return "실행 후 통계가 표시됩니다.";
  })();

  const handleRun = async () => {
    if (streaming || question.trim().length === 0) return;

    setRan(false);
    setDisplayedAnswer("");
    setNotice(null);
    setParsed(null);
    setRiskScores([]);
    setStatsReceived(false);
    setStreamOutcome("idle");
    setTopRisk(null);
    setCitations([]);
    setTraceEvents([]);
    setStreaming(true);

    let hasToken = false;
    let sawTerminalEvent = false;

    try {
      for await (const event of streamChatResponse({ message: question, threadId: threadId ?? undefined })) {
        if (event.type === "session" && isSessionData(event.data)) {
          if (event.data.thread_id) {
            setThreadId(event.data.thread_id);
          }
          setTraceEvents((current) => [
            ...current,
            { label: "session", value: event.data.thread_id ? "대화 맥락 연결" : "세션 시작" },
          ]);
          continue;
        }

        if (event.type === "parsed" && isParsedData(event.data)) {
          setRan(true);
          setParsed(event.data);
          setTraceEvents((current) => [
            ...current,
            { label: "parsed", value: `${event.data.region ?? "-"} · ${event.data.month ?? "-"}` },
          ]);
          continue;
        }

        if (event.type === "stats" && isStatsData(event.data)) {
          const nextRiskScores = event.data.risk_scores ?? [];

          setRan(true);
          setStatsReceived(true);
          setStreamOutcome("stats");
          setRiskScores(nextRiskScores);
          setTopRisk(event.data.top_risk ?? null);
          setTraceEvents((current) => [
            ...current,
            {
              label: "stats",
              value: `총 ${event.data.total_count ?? 0}건 · ${event.data.scope_used ?? "-"}`,
            },
          ]);

          if (event.data.fallback_notice) {
            setNotice({
              kind: "info",
              title: "통계 범위 안내",
              message: event.data.fallback_notice,
            });
          }
          continue;
        }

        if (event.type === "citation" && isCitationData(event.data)) {
          setCitations(event.data.ids);
          setStreamOutcome((current) => (current === "idle" ? "answer-only" : current));
          setTraceEvents((current) => [
            ...current,
            { label: "citation", value: `${event.data.ids.length}개 출처` },
          ]);
          continue;
        }

        if (event.type === "token") {
          setRan(true);
          setStreamOutcome((current) => (current === "idle" ? "answer-only" : current));
          setDisplayedAnswer((current) => {
            if (hasToken) return current + (event.content ?? "");
            hasToken = true;
            return event.content ?? "";
          });
          continue;
        }

        if (event.type === "reask") {
          const message =
            event.content ??
            (isReaskData(event.data) ? event.data.message : undefined) ??
            "지역과 시기를 조금 더 구체적으로 입력해 주세요.";

          setRan(true);
          setDisplayedAnswer(message);
          setNotice({
            kind: "info",
            title: "추가 정보가 필요합니다",
            message: "지역과 시기를 포함해 다시 질문해 주세요.",
          });
          setTraceEvents((current) => [...current, { label: "reask", value: "추가 정보 요청" }]);
          setStreamOutcome("no-stats");
          sawTerminalEvent = true;
          continue;
        }

        if (event.type === "escalate") {
          const fallback = "공식 매뉴얼에서 충분한 근거를 찾지 못했습니다.";
          const message = event.content ?? fallback;

          setRan(true);
          setDisplayedAnswer(message);
          setNotice({
            kind: "warning",
            title: "관련 기관 안내",
            message: "공식 행동요령 근거가 부족해 안전한 기관 안내로 전환했습니다.",
          });
          setTraceEvents((current) => [
            ...current,
            {
              label: "escalate",
              value: isEscalateData(event.data) ? event.data.reason ?? "근거 부족" : "근거 부족",
            },
          ]);
          setStreamOutcome("no-stats");
          sawTerminalEvent = true;
          continue;
        }

        if (event.type === "degraded") {
          setRan(true);
          setNotice({
            kind: "warning",
            title: "일부 기능 장애",
            message: "AI 답변 생성 중 일부 문제가 있어 공식 원문 안내로 전환했습니다.",
          });
          setTraceEvents((current) => [...current, { label: "degraded", value: "강등 응답" }]);
          continue;
        }

        if (event.type === "error") {
          const message =
            event.content ??
            (isErrorData(event.data) ? event.data.message ?? event.data.detail : undefined) ??
            "일시적으로 AI 서비스에 연결할 수 없습니다.";

          setRan(true);
          setDisplayedAnswer(message);
          setNotice({
            kind: "error",
            title: "요청 처리 실패",
            message: "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
          });
          setTraceEvents((current) => [...current, { label: "error", value: "서비스 오류" }]);
          setStreamOutcome("error");
          sawTerminalEvent = true;
          continue;
        }

        if (event.type === "done") {
          setStreaming(false);
          setTraceEvents((current) => [...current, { label: "done", value: "stream completed" }]);
        }
      }
    } catch {
      setRan(true);
      setStreaming(false);
      setDisplayedAnswer("스트리밍 응답을 처리하는 중 오류가 발생했습니다.");
      setNotice({
        kind: "error",
        title: "스트리밍 오류",
        message: "네트워크 연결 또는 백엔드 응답 형식을 확인해 주세요.",
      });
      setStreamOutcome("error");
    } finally {
      if (sawTerminalEvent) {
        setStreaming(false);
      }
    }
  };

  const handleResetConversation = () => {
    if (streaming) return;

    setThreadId(null);
    setQuestion("");
    setRan(false);
    setDisplayedAnswer("");
    setNotice(null);
    setParsed(null);
    setRiskScores([]);
    setStatsReceived(false);
    setStreamOutcome("idle");
    setTopRisk(null);
    setCitations([]);
    setTraceEvents([]);
  };

  return (
    <div
      className="min-h-screen w-full text-[#1a2940]"
      style={{
        background:
          "radial-gradient(circle at top left, rgba(125, 211, 252, 0.28), transparent 30%), radial-gradient(circle at bottom right, rgba(45, 212, 191, 0.18), transparent 32%), linear-gradient(180deg, #f7fbff 0%, #eef7ff 100%)",
        fontFamily: "'Noto Sans KR', system-ui, sans-serif",
      }}
    >
      <nav className="sticky top-0 z-30 flex items-center justify-between border-b border-white/60 bg-white/35 px-6 py-3 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-[#1d6fb8] to-[#2c8fd4]">
            <Shield size={18} color="#fff" />
          </div>
          <div>
            <span className="text-base font-bold tracking-tight text-[#1a2940]">
              SafetyTrip
            </span>
            <span className="ml-2 text-xs text-[#5a7394]">여행 안전 리포트</span>
          </div>
        </div>

        <div className="flex items-center gap-2 rounded-full border border-green-300/70 bg-green-100/50 px-3 py-1.5 text-xs font-medium text-green-800">
          <CheckCircle2 size={13} />
          {statsReceived ? "Live API responded" : "Live API connected"}
        </div>
      </nav>

      <main className="mx-auto grid max-w-7xl gap-5 px-4 py-6">
        <div className="grid gap-5 lg:grid-cols-[5fr_7fr]">
          <section className="flex flex-col gap-4">
            <div className="rounded-xl border border-white/70 bg-white/60 p-4 shadow-[0_4px_24px_rgba(100,160,220,0.12)] backdrop-blur-xl">
              <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-[#5a7394]">
                여행 안전 질문
              </label>
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                rows={3}
                className="w-full resize-none rounded-lg border border-black/10 bg-white/45 px-3 py-2.5 text-sm leading-relaxed text-[#1a2940] outline-none transition focus:border-[#2c8fd4] focus:ring-4 focus:ring-sky-100"
              />
              <button
                type="button"
                onClick={handleRun}
                disabled={streaming || question.trim().length === 0}
                className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg bg-[#1d6fb8] px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-[#155d9c] disabled:cursor-wait disabled:bg-slate-400"
              >
                <Play size={16} />
                {streaming ? "분석 중" : "실행"}
              </button>
              <div className="mt-3 flex items-center justify-between gap-3 text-xs text-[#5a7394]">
                <span>{threadId ? "대화 맥락 유지 중" : "새 대화 세션"}</span>
                <button
                  type="button"
                  onClick={handleResetConversation}
                  disabled={streaming || (!threadId && !ran && question.length === 0)}
                  className="flex items-center gap-1 rounded-md px-2 py-1 font-medium text-[#1d6fb8] transition hover:bg-sky-50 disabled:cursor-not-allowed disabled:text-slate-400"
                >
                  <RotateCcw size={13} />
                  새 대화
                </button>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
              {parsedCards.map((item) => {
                const Icon = item.icon;
                return (
                  <div
                    key={item.label}
                    className="rounded-xl border border-white/70 bg-white/55 p-4 shadow-[0_3px_18px_rgba(100,160,220,0.10)] backdrop-blur-xl"
                  >
                    <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-[#5a7394]">
                      <Icon size={14} />
                      {item.label}
                    </div>
                    <div className="text-base font-semibold text-[#1a2940]">
                      {ran ? item.value : "-"}
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="rounded-xl border border-white/70 bg-white/50 p-4 backdrop-blur-xl">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-[#1a2940]">
                <Activity size={16} />
                Event Trace
              </div>
              <div className="space-y-2">
                {traceEvents.length === 0 ? (
                  <p className="text-xs text-[#5a7394]">실행 후 백엔드 이벤트가 표시됩니다.</p>
                ) : (
                  traceEvents.map((event, index) => (
                    <div
                      key={`${event.label}-${index}`}
                      className="flex items-center justify-between rounded-lg border border-white/60 bg-white/45 px-3 py-2"
                    >
                      <span className="font-mono text-xs text-[#1d6fb8]">{event.label}</span>
                      <span className="text-right text-xs text-[#5a7394]">{event.value}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </section>

          <section className="rounded-xl border border-white/75 bg-white/60 p-5 shadow-[0_6px_32px_rgba(80,140,200,0.13)] backdrop-blur-xl">
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[#5a7394]">
                  <AlertTriangle size={14} />
                  Risk Summary
                </div>
                <h1 className="mt-1 text-2xl font-bold tracking-tight text-[#1a2940]">
                  {analysisTitle}
                </h1>
              </div>
              {topRisk && (
                <div className="rounded-full border border-orange-200 bg-orange-100/70 px-3 py-1.5 text-xs font-semibold text-orange-700">
                  상위 위험: {topRisk}
                </div>
              )}
            </div>

            <div className="grid gap-4 xl:grid-cols-[1fr_1.2fr]">
              <div className="rounded-xl border border-white/70 bg-white/45 p-4">
                <div className="mb-3 text-sm font-semibold text-[#1a2940]">
                  위험도 점수
                </div>
                <div className="h-64">
                  {chartData.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={chartData} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(90,115,148,0.18)" />
                        <XAxis dataKey="name" tickLine={false} axisLine={false} />
                        <YAxis tickLine={false} axisLine={false} />
                        <Tooltip content={<RiskTooltip />} />
                        <Bar dataKey="score" radius={[8, 8, 0, 0]}>
                          {chartData.map((item) => (
                            <Cell key={item.name} fill={item.color} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="flex h-full items-center justify-center text-sm text-[#5a7394]">
                      {riskEmptyMessage}
                    </div>
                  )}
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2">
                  {chartData.map((item) => {
                    const Icon = getRiskStyle(item.name).icon;
                    return (
                      <div key={item.name} className="rounded-lg bg-white/55 px-2 py-2 text-center">
                        <div className="mb-1 flex justify-center" style={{ color: item.color }}>
                          <Icon size={15} />
                        </div>
                        <div className="text-xs font-semibold text-[#1a2940]">{item.name}</div>
                        <div className="text-[11px] text-[#5a7394]">{item.count}건</div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="rounded-xl border border-white/70 bg-white/45 p-4">
                <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-[#1a2940]">
                  <BookOpen size={16} />
                  안전 리포트
                </div>
                <div className="h-[310px] overflow-y-auto overscroll-contain rounded-lg border border-white/60 bg-white/45 p-4 pr-3">
                  {notice && (
                    <div className={noticeClassName(notice.kind)}>
                      <div className="mb-1 font-semibold">{notice.title}</div>
                      <div>{notice.message}</div>
                    </div>
                  )}
                  {displayedAnswer ? (
                    renderAnswer(displayedAnswer)
                  ) : (
                    <p className="text-sm text-[#5a7394]">
                      실행을 누르면 백엔드 SSE 응답이 스트리밍됩니다.
                    </p>
                  )}
                  {streaming && <span className="ml-1 inline-block h-4 w-1 animate-pulse bg-[#1d6fb8]" />}
                </div>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              {citations.map((citation) => (
                <span
                  key={citation}
                  className="rounded-full border border-sky-200 bg-sky-100/70 px-3 py-1.5 text-xs font-semibold text-sky-800"
                >
                  {citation}
                </span>
              ))}
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
