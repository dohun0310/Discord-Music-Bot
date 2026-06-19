FROM python:3.14-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      gcc \
      libffi-dev \
      build-essential \
      ffmpeg && \
    apt-get clean -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "app"]