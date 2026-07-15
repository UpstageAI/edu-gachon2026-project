# SafetyTrip2026 FE

SafetyTrip의 프론트엔드 파트입니다.

<img width="1439" height="761" alt="image" src="https://github.com/user-attachments/assets/5c52392b-5832-438f-a723-42c53de6762d" />


현재 구성한 것은 다음과 같습니다.
1. React/Vite 기반으로 여행 안전 리포트 화면을 구성
2. 백엔드 연동 전 mock 시나리오로 핵심 흐름을 확인

## 실행 방법

1. 레포지토리를 클론합니다.

```bash
git clone https://github.com/SafetyTrip2026/FE.git
cd FE
```

2. 의존성을 설치합니다.

```bash
npm install
```

3. 개발 서버를 실행합니다.

```bash
npm run dev
```

4. 터미널에 표시되는 Vite 주소로 접속합니다. 보통 아래 주소입니다.

```text
http://localhost:5173
```

참고: 현재 화면은 백엔드 연결 전 mock 시나리오로 동작합니다. 백엔드 API가 준비되면 `.env`의 `VITE_API_BASE_URL` 값을 실제 백엔드 주소로 바꾸면 됩니다.

## 환경변수 목록

- `VITE_API_BASE_URL`: 백엔드 API 서버 주소
- `VITE_USE_MOCK`: 백엔드 연동 전 mock 사용 여부


## 백엔드 API 계약

이 프론트는 최종적으로 백엔드의 스트리밍 API와 연결될 예정입니다.
백엔드 연동 전까지는 `src/mocks/safetyTripMock.ts` 안의 mock 데이터를 사용합니다.

## Mock 시나리오

사용자 질문:

```text
8월 초에 부모님 모시고 부산 해운대 가는데 주의할 게 있을까?
```

화면에 표시되는 mock 결과:

- 지역: 부산 해운대구
- 시기: 8월 초
- 동반자: 고령자(부모님)
- 주요 위험: 폭염, 호우, 태풍
- 차트 점수: 폭염 88, 호우 72, 태풍 61
- 출처: `GUIDE-HEAT-ELDERLY-001`, `GUIDE-RAIN-FLOOD-002`
- 이벤트 흐름: `parsed -> stats -> token -> citation -> done`

Mock 데이터 위치:

```text
src/app/App.tsx
```

주요 상수:

```text
FULL_ANSWER
RISK_DATA
TRACE_EVENTS
PARSED_CARDS
CITATIONS
```

## 파일 구조

```text
SafetyTrip2026-FE/
  src/
    main.tsx
    app/
      App.tsx
    mocks/
      safetyTripMock.ts
    styles/
      fonts.css
      globals.css
      index.css
      tailwind.css
      theme.css
  index.html
  package.json
  package-lock.json
  vite.config.ts
  .env.example
  .gitignore
  README.md
```

주요 파일 설명:

- `src/main.tsx`: React 앱 시작점
- `src/app/App.tsx`: 현재 메인 화면과 mock 시나리오
- `src/app/components/figma/ImageWithFallback.tsx`: 이미지 로딩 실패 시 대체 UI를 보여주는 Figma export 컴포넌트
- `src/app/components/ui/`: Figma/shadcn 기반 UI 컴포넌트
- `src/styles/`: Tailwind 및 테마 스타일
- `index.html`: Vite 진입 HTML
- `package.json`: 실행 스크립트와 의존성
- `package-lock.json`: npm 의존성 버전 고정 파일
- `vite.config.ts`: Vite, React, Tailwind 설정
- `.env.example`: 로컬 환경변수 예시
- `.gitignore`: Git에 올리지 않을 파일 목록
- `README.md`: 프로젝트 실행 및 구조 설명
