// 아주 가벼운 마크다운 렌더러 — 새 의존성 추가 없이(react-markdown 등 미사용)
// agent가 SUMMARY 프롬프트로 생성하는 응답에 흔히 나오는 패턴만 처리한다:
//   **볼드**, `코드`, 줄바꿈 단락, "1. 2. 3." 형태의 번호 목록(줄바꿈 없이 이어져도 인식),
//   "- " / "* " 형태의 불릿 목록.
// 그 외 패턴은 원문 그대로 보여준다(안전한 폴백).

function renderInline(text, keyPrefix) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (!part) return null;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={`${keyPrefix}-${i}`}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code key={`${keyPrefix}-${i}`} className="md-code">
          {part.slice(1, -1)}
        </code>
      );
    }
    return part;
  });
}

// "... 1. AAA 2. BBB 3. CCC" 처럼 줄바꿈 없이 이어진 번호 목록도 인식한다.
// agent 응답이 항상 줄바꿈을 넣어주지는 않기 때문 — 숫자가 1부터 순서대로 나올 때만 목록으로 인정해
// "가격은 1.5배" 같은 소수점 표현을 오인식하지 않도록 한다(한국어 큰 수는 쉼표 표기라 충돌 적음).
function splitNumberedList(text) {
  const marker = /(?:^|\s)(\d+)\.\s+/g;
  const matches = [...text.matchAll(marker)];
  if (matches.length < 2) return null;
  const nums = matches.map((m) => parseInt(m[1], 10));
  const sequential = nums.every((n, i) => n === i + 1);
  if (!sequential) return null;

  const items = [];
  for (let i = 0; i < matches.length; i++) {
    const start = matches[i].index + matches[i][0].length;
    const end = i + 1 < matches.length ? matches[i + 1].index : text.length;
    const item = text.slice(start, end).trim();
    if (item) items.push(item);
  }
  const preamble = text.slice(0, matches[0].index).trim();
  return { preamble, items };
}

function splitBulletList(text) {
  const lines = text.split("\n").map((l) => l.trim());
  const isBulletLine = (l) => /^[-*]\s+/.test(l);
  if (!lines.some(isBulletLine)) return null;
  const items = [];
  const rest = [];
  let sawBullet = false;
  for (const l of lines) {
    if (isBulletLine(l)) {
      sawBullet = true;
      items.push(l.replace(/^[-*]\s+/, ""));
    } else if (!sawBullet) {
      rest.push(l);
    }
  }
  if (items.length < 1) return null;
  return { preamble: rest.join(" ").trim(), items };
}

function renderBlock(block, bi) {
  const numbered = splitNumberedList(block);
  if (numbered) {
    return (
      <div key={bi} className="md-block">
        {numbered.preamble ? <p>{renderInline(numbered.preamble, `${bi}-pre`)}</p> : null}
        <ol>
          {numbered.items.map((item, ii) => (
            <li key={ii}>{renderInline(item, `${bi}-${ii}`)}</li>
          ))}
        </ol>
      </div>
    );
  }

  const bulleted = splitBulletList(block);
  if (bulleted) {
    return (
      <div key={bi} className="md-block">
        {bulleted.preamble ? <p>{renderInline(bulleted.preamble, `${bi}-pre`)}</p> : null}
        <ul>
          {bulleted.items.map((item, ii) => (
            <li key={ii}>{renderInline(item, `${bi}-${ii}`)}</li>
          ))}
        </ul>
      </div>
    );
  }

  return <p key={bi}>{renderInline(block, `${bi}`)}</p>;
}

export default function Markdown({ text, className, style }) {
  if (!text) return null;
  const blocks = text
    .split(/\n{2,}|\n/)
    .map((b) => b.trim())
    .filter(Boolean);
  const finalBlocks = blocks.length > 0 ? blocks : [text];

  return (
    <div className={"md-body" + (className ? " " + className : "")} style={style}>
      {finalBlocks.map(renderBlock)}
    </div>
  );
}

// History/Saved 같은 한 줄 미리보기용 — 마크다운 기호만 지우고 렌더링은 하지 않는다
// (text-overflow: ellipsis 로 한 줄만 보여주는 카드라 굳이 블록 렌더링을 할 필요가 없음).
export function stripMarkdown(text) {
  if (!text) return "";
  return text
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\n+/g, " ")
    .trim();
}
