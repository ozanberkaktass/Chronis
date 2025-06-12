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

# Docker socket için hacim oluştur
VOLUME /var/run/docker.sock

# Docker socket'ini doğru izinlerle erişilebilir yapma
RUN ln -sf /var/run/docker.sock /tmp/docker.sock && \
    chmod 666 /tmp/docker.sock || true

EXPOSE 5000

# Docker socket'i hazırla ve uygulamayı başlat
CMD ["sh", "-c", "chmod 666 /var/run/docker.sock || true && python app.py"] 