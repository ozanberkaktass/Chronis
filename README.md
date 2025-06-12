# Chronis - Docker Container Yönetim Uygulaması

Linux üzerinde çalışan, Docker container'larını web arayüzü ile yönetmenizi sağlayan uygulama.

## Özellikler

- Container listesi görüntüleme
- Container başlatma/durdurma/silme
- Container detaylarını görüntüleme
- Container log'larını görüntüleme
- Image yönetimi

## Kurulum

```bash
# Repoyu klonlayın
git clone https://github.com/yourusername/chronis.git
cd chronis

# Docker ile çalıştırın
docker-compose up -d
```

## Geliştirme

```bash
# Gerekli bağımlılıkları kurun
pip install -r requirements.txt

# Geliştirme modunda çalıştırın
python app.py
```

## Teknolojiler

- Backend: Flask (Python)
- Frontend: HTML, CSS, JavaScript
- Container Yönetimi: Docker API 