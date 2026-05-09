FROM python:3.11-slim

LABEL maintainer="xfengyin"
LABEL description="知乎盐选小说下载器"

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/cache /app/output

RUN chmod +x /app/cli.py

ENTRYPOINT ["python", "/app/cli.py"]
CMD ["--help"]
