FROM node:20-alpine AS builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

ARG VITE_API_BASE=/api/v1
ARG VITE_AGENT_MODE=full_react
ENV VITE_API_BASE=${VITE_API_BASE}
ENV VITE_AGENT_MODE=${VITE_AGENT_MODE}

RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /frontend/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
