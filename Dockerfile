FROM node:20-slim AS frontend-build

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --frozen-lockfile 2>/dev/null || npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /opt/reg-gpt

# 系统依赖：ca-certificates + Playwright Chromium 运行时所需的库
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
       libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
       libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
       libcairo2 libasound2 libxshmfence1 libx11-xcb1 \
       fonts-liberation fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /tmp/requirements.txt \
    && python -m playwright install chromium

COPY backend/openai_reg.py /opt/reg-gpt/openai_reg.py
COPY backend/reg_gpt /opt/reg-gpt/reg_gpt
COPY --from=frontend-build /build/dist /opt/reg-gpt/frontend/dist

CMD ["python", "-u", "openai_reg.py"]
