FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

WORKDIR /app

COPY huntera/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY huntera/ ./huntera/
COPY railway.json .

ENV PORT=5000
EXPOSE 5000

CMD ["python", "huntera/monitor_huntera.py"]
