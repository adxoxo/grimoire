# Stage 1: build the dashboard
FROM node:24-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: python runtime serving the API + the built dashboard
FROM python:3.12-slim
WORKDIR /app

COPY pyproject.toml ./
COPY grimoire/ ./grimoire/
RUN pip install --no-cache-dir .

COPY --from=web /web/dist ./frontend/dist

EXPOSE 8731
CMD ["uvicorn", "grimoire.api:app", "--host", "0.0.0.0", "--port", "8731"]
