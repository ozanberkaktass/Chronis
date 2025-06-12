FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Unix socket işlemi için gerekli paketleri yükle
RUN apt-get update && \
    apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    libffi-dev \
    libssl-dev \
    python3-dev \
    socat \
    procps \
    iproute2

# Docker CLI kurulumu
RUN curl -fsSL https://download.docker.com/linux/debian/gpg | apt-key add - && \
    echo "deb [arch=amd64] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    apt-get update && \
    apt-get install -y docker-ce-cli && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY . .

# Docker socket hacim noktasını hazırla - socket dosyasını önceden oluşturmuyoruz
RUN mkdir -p /docker-socket

EXPOSE 5000

# Uygulamayı başlat
CMD ["python", "app.py"] 