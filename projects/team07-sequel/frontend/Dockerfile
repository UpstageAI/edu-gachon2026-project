# ---- 1단계: 빌드 ----
# Vite/React 소스를 정적 파일(dist/)로 빌드하는 단계.
# 이 단계에서 만든 node_modules 등은 최종 이미지에 포함되지 않는다 (멀티 스테이지 빌드).
FROM node:20-alpine AS build

WORKDIR /app

# package.json/lock 파일만 먼저 복사해서 의존성 설치 레이어를 캐싱한다.
# (소스 코드만 바뀌고 의존성이 그대로면 npm install을 다시 안 해도 되어 빌드가 빨라짐)
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

# Vite는 빌드 "시점"에 환경변수를 정적 파일 안에 박아넣는다 (런타임에 못 바꿈).
# 그래서 배포용 백엔드 URL을 빌드 인자로 받아서 빌드 전에 주입한다.
# 기본값은 현재 배포된 Cloud Run 백엔드 URL. CI에서 --build-arg로 덮어쓸 수 있다.
ARG VITE_API_BASE_URL=https://text2sql-backend-267324339574.asia-northeast3.run.app
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# ---- 2단계: 서빙 ----
# 빌드 결과물(dist/, 정적 HTML/JS/CSS)만 가벼운 nginx 이미지에 담아 서빙한다.
FROM nginx:1.27-alpine

# Cloud Run은 컨테이너가 반드시 PORT(기본 8080)에서 리스닝해야 한다.
# nginx 기본 설정은 80번 포트라 8080으로 바꾼 커스텀 설정을 사용한다.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
