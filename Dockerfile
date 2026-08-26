FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libwayland-client0 \
    libwayland-egl1 \
    libwayland-server0 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir playwright==1.52.0 \
    && playwright install chromium \
    && playwright install-deps chromium

WORKDIR /app

COPY huntera/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY huntera/ ./huntera/

ENV PORT=5000
EXPOSE 5000

CMD ["python", "huntera/monitor_huntera.py"]
