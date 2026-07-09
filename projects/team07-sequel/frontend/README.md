# Text2SQL Frontend

React(Vite) 기반 채팅형 프론트엔드. 자연어로 질문을 입력하면 백엔드의 `/api/query`를
SSE(Server-Sent Events)로 호출해서, 진행 상태 → 결과 표/요약 → SQL 원문을 실시간으로 보여준다.

## 폴더 구조

```
Frontend/
├── index.html
├── vite.config.js
├── package.json
└── src/
    ├── main.jsx                  # React 엔트리포인트
    ├── App.jsx                   # 채팅 UI 전체 (입력창, 메시지 목록, 상태 관리)
    ├── index.css                 # 전체 스타일
    ├── api/queryStream.js        # 백엔드 SSE 스트림을 fetch로 직접 파싱하는 클라이언트
    └── components/ResultTable.jsx # 조회 결과를 표로 렌더링
```

## 백엔드와 통신하는 방식

브라우저 기본 `EventSource`는 GET 요청만 지원해서 POST 바디(질문 내용)를 보낼 수 없다.
그래서 `api/queryStream.js`에서 `fetch` + `ReadableStream`으로 SSE 프레이밍
(`event: ...\ndata: ...\n\n`)을 직접 파싱한다.

`App.jsx`는 이벤트 타입별로 화면을 갱신한다.

| 이벤트 | 화면 반응 |
|---|---|
| `status` | 말풍선에 "쿼리를 생성하는 중…" 같은 상태 문구 표시 |
| `result` | 표(`ResultTable`) + 자연어 요약 표시 |
| `sql` | "SQL 보기" 토글 버튼 활성화 (기본은 숨김) |
| `error` | 에러 전용 스타일로 메시지 표시 |
| `done` | 스트림 종료 |

세션 식별자(`session_id`)는 브라우저 탭을 새로고침하기 전까지 하나로 유지되며,
후속 질문("그 중에 1위만 알려줘" 등) 시 백엔드가 이전 대화 맥락을 이어갈 수 있도록
매 요청에 함께 전달된다.

## 로컬 실행

### 1) 환경변수

```bash
cp .env.example .env
```

```dotenv
VITE_API_BASE_URL=http://localhost:8080
```

백엔드가 실행 중인 주소를 가리키면 된다. 배포 시에는 실제 Cloud Run 백엔드 URL로 교체.

### 2) 설치 및 실행

```bash
npm install
npm run dev
```

`http://localhost:5173` 접속 후, 백엔드(`localhost:8080`)가 함께 떠 있어야 정상 동작한다.

### 3) 프로덕션 빌드

```bash
npm run build   # dist/ 에 정적 파일 생성
npm run preview # 빌드 결과 미리보기
```

## 현재 상태 / TODO

- **핵심 기능은 구현 및 검증 완료**: 채팅 입력, 실시간 스트리밍 상태 표시, 결과 표/요약,
  SQL 토글, 세션 기반 후속 질문까지 목업 백엔드 응답으로 엔드투엔드 확인됨.
- **Dockerfile 미작성**: 배포용 컨테이너화(정적 파일 빌드 후 서빙)는 아직 하지 않음.
- **부가 기능 미착수**: 로딩 애니메이션 디테일, 대화 목록 저장/복원, 모바일 반응형,
  질문 자동완성/예시 질문 추천 등은 핵심 기능 확정 후 진행 예정.
- **에러 문구 다국어/문구 다듬기**: 지금은 백엔드가 보낸 메시지를 그대로 노출.
