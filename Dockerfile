FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Docker komutları için Docker CLI yükle
RUN apt-get update && \
    apt-get install -y curl && \
    curl -fsSL https://get.docker.com/builds/Linux/x86_64/docker-latest.tgz | tar -xzC /usr/local/bin --strip=1 docker/docker && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Docker socket için hacim oluştur
VOLUME /var/run/docker.sock

EXPOSE 5000

CMD ["python", "app.py"] 