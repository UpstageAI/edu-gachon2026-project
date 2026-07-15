# TripRoute UI 디자인 스펙 (Chat A.I+ 스타일)

현재 `ui/gradio_app.py`의 Gradio 인터페이스에 첨부 이미지("CHAT A.I+")의 톤앤매너를 적용하기 위한 디자인 스펙입니다. 인디고/퍼플 포인트 컬러 + 라벤더빛 외곽 배경 + 화이트 카드형 대화창 구조가 핵심입니다.

---

## 1. 컬러 팔레트

| 용도 | 값 | 설명 |
|---|---|---|
| 페이지 바탕 (제일 바깥) | `#C9D6F2` | 은은한 라벤더 블루, 카드 뒤로 살짝 보이는 배경 |
| 앱 카드 배경 | `#FFFFFF` | 사이드바 + 메인 채팅 영역을 감싸는 큰 흰 카드 (라운드 24px) |
| 사이드바 배경 | `#FFFFFF` | 메인과 동일 (구분은 보더로) |
| 포인트 컬러 (primary) | `#6C63FF` | 인디고/퍼플 — 버튼, 링크, 선택 상태, 아바타 링 |
| 포인트 hover / active | `#5A52E0` | 버튼 hover, 진한 인디고 |
| 사용자 채팅 텍스트/아이콘 | `#111111` | 유저 발화는 아바타만, 텍스트는 진회색 |
| 본문 텍스트 | `#1A1A1A` | AI 응답 본문 (거의 블랙) |
| 보조 텍스트 | `#8B8D98` | 대화 목록 항목, 타임스탬프, placeholder |
| 테두리 | `#EDEDF2` | 카드 내부 구분선, 리스트 아이템 hover 보더 |
| 사이드바 선택 항목 배경 | `#EEF0FC` | 현재 선택된 대화 항목 하이라이트 (연한 인디고) |
| 유저 아바타 링 | `#6C63FF` | 아바타 테두리 포인트 |
| 강조 배지 ("Upgrade to Pro" 류) | `#6C63FF` → `#8B7CFF` 그라디언트 | 우측 리본 배지 (선택 요소, TripRoute에선 "Pro" 배지 대신 없어도 무방) |

⚠️ 대비 체크: 흰 배경(`#FFFFFF`) 위 `#6C63FF` 텍스트/아이콘은 대비 ≈4.6:1로 AA 통과. 버튼 흰 텍스트(`#FFFFFF` on `#6C63FF`)는 ≈4.6:1로 일반 텍스트도 AA 통과.

다크 모드는 별도 요청 시 정의(현재 스펙은 라이트 모드 기준).

---

## 2. 타이포그래피

- Sans 계열 통일: `"Pretendard", "Inter", -apple-system, sans-serif`
- 로고("CHAT A.I+" 자리에 해당하는 타이틀)는 넓은 자간(`letter-spacing: 0.15em`)의 대문자 bold
- 본문 15~16px, line-height 1.6
- 사이드바 대화 목록 항목은 14px, `#1A1A1A`(선택 시) / `#4A4A55`(기본)

---

## 3. 레이아웃 구조

전체를 **2단 구조**로 재설계합니다 (기존 상단 옵션 박스 + 세로 챗봇 구조 → 좌측 사이드바 + 우측 채팅 패널).

```
┌───────────────────────────────────────────────────────┐
│  전체 바탕 #C9D6F2                                       │
│  ┌──────────────┬──────────────────────────────────┐  │
│  │ 사이드바 (280px) │  채팅 영역 (나머지, max 1050px)     │  │
│  │  - 로고           │  - 유저 발화(우측, 아바타+텍스트) │  │
│  │  - New chat 버튼  │  - AI 응답(좌측, 로고뱃지+본문)   │  │
│  │  - 검색 아이콘    │  - 하단 고정 입력창                │  │
│  │  - 대화 목록      │                                  │  │
│  │  - Settings/유저  │                                  │  │
│  └──────────────┴──────────────────────────────────┘  │
└───────────────────────────────────────────────────────┘
```

- 바깥 카드: `border-radius: 24px`, `box-shadow: 0 20px 60px rgba(40,50,110,0.15)`, 최대 폭 1440px 중앙 정렬
- 사이드바 폭 280px, 내부 패딩 24px
- 채팅 영역 패딩 32~40px, 하단 입력창은 sticky

---

## 4. 컴포넌트별 적용

### 4.1 사이드바
- 상단 로고 텍스트(예: "TRIP ROUTE") — 넓은 자간 bold
- **New chat** 버튼: `#6C63FF` 배경, 흰 텍스트, pill 형태(`border-radius: 999px`), 좌측 `+` 아이콘, 옆에 검은 원형 검색 버튼(`background:#111`, 흰 아이콘) 배치
- **대화 목록**: 아이콘(말풍선) + 제목 텍스트, hover 시 `#F7F7FB` 배경, 선택된 항목은 `#EEF0FC` 배경 + `#6C63FF` 텍스트 + 우측에 삭제/수정 아이콘과 진행중 표시(작은 인디고 dot)
- 리스트 그룹 헤더("Your conversations", "Last 7 Days")는 `#8B8D98`, 11px, uppercase 살짝
- 하단: Settings 항목(아이콘+텍스트, 연회색 배경 pill) + 유저 프로필(아바타+이름, 보더 pill)

### 4.2 채팅 영역
- 유저 메시지: 우측 상단에 작은 원형 아바타 + 메시지 텍스트(카드/버블 없이 순수 텍스트, 우측 정렬), 우측 끝에 편집 아이콘
- AI 응답: 좌측에 브랜드 배지(작은 pill, 인디고 텍스트 + 회전 아이콘, 예: "TRIPROUTE AI ↻"), 본문은 카드 없이 흐르는 텍스트, 리스트/번호목록은 굵은 항목명 + 설명 구조 유지
- 응답 하단 액션바: 👍 👎 복사 아이콘(연회색, 구분선으로 분리) + 우측 "Regenerate" pill 버튼(연회색 배경, 아이콘+텍스트)
- 메시지 사이 구분선: `1px solid #EDEDF2`

### 4.3 여행 계획 결과(다중 markdown 표) 처리
- TripRoute 특유의 다중 표(일정표/동선/비용표 등)는 채팅 스트림 버블에 밀어넣지 않고, AI 응답 영역 안에서 표마다 카드로 감싸 구분: 배경 `#FAFAFC`, 보더 `1px solid #EDEDF2`, `border-radius: 16px`, 내부 패딩 16px, 표 사이 간격 16px
- 표 헤더 배경 `#F1F1FA`, 헤더 텍스트 `#4A4A55`
- React trace(디버그) 표는 `gr.Accordion("실행 과정 보기", open=False)`로 기본 접어둠 (유지)

### 4.4 입력창
- 하단 고정, 배경 `#FFFFFF`, 보더 `1px solid #EDEDF2`, `border-radius: 28px`(필 형태), 그림자 `0 8px 24px rgba(40,50,110,0.08)`
- 좌측에 작은 이모지/아이콘 슬롯, placeholder "What's in your mind?..." 스타일 → TripRoute는 "어떤 여행을 계획할까요?" 등으로 대체
- 우측 원형 전송 버튼: `#6C63FF` 배경, 흰 종이비행기 아이콘, hover `#5A52E0`
- `value=DEFAULT_MESSAGE` 대신 `placeholder=DEFAULT_MESSAGE` 유지 (기존 지적사항 동일 적용)

### 4.5 버튼 공통 규칙
- Primary: `#6C63FF` 배경, 흰 텍스트, pill 라운드, hover `#5A52E0`
- Secondary(예: 대화 초기화, Regenerate): 배경 `#F3F3F8`, 텍스트 `#4A4A55`, 보더 없음, pill 라운드
- 아이콘 버튼(검색, 편집, 삭제): 원형, 기본 `#F3F3F8` 배경 또는 투명, hover 시 `#EDEDF2`

---

## 5. CSS 초안 (`ui/gradio_app.py`의 `CUSTOM_CSS` 대체용)

```css
:root {
    --tr-outer-bg: #C9D6F2;
    --tr-card-bg: #FFFFFF;
    --tr-primary: #6C63FF;
    --tr-primary-hover: #5A52E0;
    --tr-text: #1A1A1A;
    --tr-text-muted: #8B8D98;
    --tr-border: #EDEDF2;
    --tr-selected-bg: #EEF0FC;
    --tr-pill-bg: #F3F3F8;
}

body {
    background: var(--tr-outer-bg) !important;
}

.gradio-container {
    max-width: 1440px !important;
    margin: 40px auto !important;
    background: var(--tr-card-bg) !important;
    border-radius: 24px !important;
    box-shadow: 0 20px 60px rgba(40, 50, 110, 0.15);
    font-family: "Pretendard", "Inter", -apple-system, sans-serif;
    overflow: hidden;
}

#sidebar {
    background: var(--tr-card-bg);
    border-right: 1px solid var(--tr-border);
    padding: 24px;
    min-width: 280px;
}

#title-box h1 {
    color: var(--tr-text);
    font-weight: 700;
    letter-spacing: 0.15em;
    text-transform: uppercase;
}

#new-chat-button {
    background: var(--tr-primary) !important;
    color: #fff !important;
    border-radius: 999px !important;
    font-weight: 700;
}
#new-chat-button:hover {
    background: var(--tr-primary-hover) !important;
}

.conversation-item {
    border-radius: 12px;
    padding: 10px 12px;
    color: #4A4A55;
}
.conversation-item:hover {
    background: #F7F7FB;
}
.conversation-item.selected {
    background: var(--tr-selected-bg);
    color: var(--tr-primary);
}

#chatbot {
    background: var(--tr-card-bg);
    min-height: 520px;
}

/* 유저/AI 발화 모두 무카드, 구분선만 */
#chatbot .message-row {
    border-bottom: 1px solid var(--tr-border);
    padding: 20px 0;
}

/* 여행 계획 결과 표 카드 */
#chatbot table {
    background: #FAFAFC;
    border: 1px solid var(--tr-border);
    border-radius: 16px;
    border-collapse: collapse;
    overflow: hidden;
}
#chatbot th {
    background: #F1F1FA;
    color: #4A4A55;
    padding: 8px 12px;
}
#chatbot td {
    padding: 8px 12px;
    border-top: 1px solid var(--tr-border);
}

#message-input textarea {
    border-radius: 28px !important;
    border: 1px solid var(--tr-border) !important;
    box-shadow: 0 8px 24px rgba(40, 50, 110, 0.08);
}
#message-input textarea:focus {
    border-color: var(--tr-primary) !important;
}

#send-button {
    background: var(--tr-primary) !important;
    color: #fff !important;
    border-radius: 50% !important;
    min-width: 44px;
    min-height: 44px;
}
#send-button:hover {
    background: var(--tr-primary-hover) !important;
}

.secondary-pill {
    background: var(--tr-pill-bg) !important;
    color: #4A4A55 !important;
    border-radius: 999px !important;
    border: none !important;
}
```

⚠️ `#sidebar`, `.conversation-item`, `.message-row` 등은 Gradio 기본 컴포넌트에 없는 클래스이므로, `elem_id`/`elem_classes`를 직접 지정하거나 `gr.Row`/`gr.Column` 커스텀 레이아웃으로 구조를 새로 짜야 합니다. Gradio 버전 업그레이드 시 실제 렌더링을 재확인하세요.

---

## 6. 정보구조 재설계

- 기존: 상단 가로 옵션 박스 + 아래 세로 챗봇 한 컬럼
- 변경: **좌측 사이드바(대화 목록/설정) + 우측 채팅 컬럼** 2단 구조로 전환
- 여행 계획 옵션(기존 `.option-box` 슬라이더/라디오)은 사이드바 하단 또는 채팅 입력창 위 접이식 패널로 이동
- 여행 계획 결과(다중 표)는 AI 응답 영역 내부에서 표 단위 카드로 구분(§4.3), 별도 탭 분리는 선택사항

---

## 7. 적용 우선순위

1. **2단 레이아웃(사이드바 + 채팅 컬럼) 구조 변경** (§3, §6)
2. **컬러 팔레트 교체** — 라벤더 배경 + 인디고 포인트 (§1, §5)
3. **사이드바 컴포넌트(New chat, 검색, 대화 목록, Settings/유저) 구현** (§4.1)
4. **채팅 영역 무카드 스트림 + 액션바 + 표 카드 스타일** (§4.2, §4.3)
5. **입력창 pill 스타일 + 원형 전송 버튼** (§4.4)
6. **React trace 기본 숨김 + 입력창 placeholder 전환** (기존 지적사항 유지)
</content>
</invoke>
