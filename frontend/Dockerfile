# --- build stage: compile the React app to static files ---
FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# --- runtime stage: unprivileged nginx serving dist/ on port 3000 ---
FROM nginxinc/nginx-unprivileged:1.29-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
COPY docker-entrypoint.sh /docker-entrypoint.d/40-write-env.sh

USER root
RUN chown nginx:nginx /usr/share/nginx/html/env.js
USER nginx

ENV API_URL=http://localhost:8000
EXPOSE 3000
