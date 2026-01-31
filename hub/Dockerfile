# Dockerfile for LGSM Hub
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc python3-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default Hub port
EXPOSE 49950

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "49950"]
