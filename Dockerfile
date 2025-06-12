FROM python:3.9-slim

WORKDIR /app

# Docker bağımlılıklarını ve Python bağımlılıklarını kur
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    lsb-release \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI kurulumu
RUN curl -fsSL https://get.docker.com -o get-docker.sh && \
    sh get-docker.sh && \
    rm get-docker.sh

# Python bağımlılıklarını kopyala ve kur
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama dosyalarını kopyala
COPY . .

# Port 5000'i dışarı aç
EXPOSE 5000

# Uygulamayı başlat
CMD ["python", "app.py"] 