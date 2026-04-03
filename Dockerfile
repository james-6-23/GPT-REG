FROM node:20-slim AS frontend-build

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --frozen-lockfile 2>/dev/null || npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /opt/reg-gpt

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend/openai_reg.py /opt/reg-gpt/openai_reg.py
COPY backend/reg_gpt /opt/reg-gpt/reg_gpt
COPY --from=frontend-build /build/dist /opt/reg-gpt/frontend/dist

CMD ["python", "-u", "openai_reg.py"]
