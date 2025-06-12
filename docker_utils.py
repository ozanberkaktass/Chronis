import docker
import os
import logging
import time
from urllib.parse import urlparse

# Docker istemcisi için bağlantı hatalarını yönetecek yardımcı fonksiyonlar
logger = logging.getLogger(__name__)

def get_docker_client():
    """
    Docker bağlantısını farklı yöntemlerle deneyerek docker istemcisi oluşturur.
    """
    # Bağlantı seçeneklerini dene
    connection_options = [
        # Standart Docker socket
        {'base_url': 'unix:///var/run/docker.sock'},
        # Windows'ta Docker socket
        {'base_url': 'npipe:////./pipe/docker_engine'},
        # TCP bağlantısı (Docker'ın uzaktan erişim için yapılandırılması gerekir)
        {'base_url': 'tcp://localhost:2375'},
        # Çevre değişkenlerinden bağlantı
        {}
    ]
    
    last_exception = None
    
    # Her bağlantı seçeneğini dene
    for options in connection_options:
        try:
            client = docker.from_env() if not options else docker.DockerClient(**options)
            # Bağlantıyı doğrula
            client.ping()
            logger.info(f"Docker bağlantısı başarılı: {options}")
            return client
        except Exception as e:
            last_exception = e
            logger.warning(f"Docker bağlantı denemesi başarısız oldu: {options}. Hata: {str(e)}")
    
    # Docker Desktop HTTP URL şemasını dene
    try:
        client = docker.DockerClient(base_url="http://localhost:2375")
        client.ping()
        logger.info("Docker HTTP bağlantısı başarılı")
        return client
    except Exception as e:
        last_exception = e
        logger.warning(f"HTTP Docker bağlantısı başarısız: {str(e)}")
    
    # Hiçbir bağlantı çalışmadıysa son hatayı yükselt
    raise Exception(f"Docker'a bağlanılamıyor. Son hata: {str(last_exception)}")

def get_container_status(container_id):
    """Konteyner durumunu alır ve hataları ele alır"""
    try:
        client = get_docker_client()
        container = client.containers.get(container_id)
        return container.status
    except Exception as e:
        logger.error(f"Konteyner durumu alınamadı {container_id}: {str(e)}")
        return "bilinmiyor"

def list_containers(all_containers=False):
    """Tüm konteynerleri listeler ve hataları ele alır"""
    try:
        client = get_docker_client()
        return client.containers.list(all=all_containers)
    except Exception as e:
        logger.error(f"Konteynerler listelenirken hata oluştu: {str(e)}")
        return []

def retry_docker_operation(operation, max_retries=3, retry_delay=1):
    """Docker işlemlerini yeniden deneme mantığı ile yürütür"""
    retry_count = 0
    last_exception = None
    
    while retry_count < max_retries:
        try:
            return operation()
        except Exception as e:
            last_exception = e
            retry_count += 1
            logger.warning(f"Docker işlemi başarısız oldu, {retry_count}/{max_retries} deneniyor. Hata: {str(e)}")
            time.sleep(retry_delay)
    
    # Tüm denemeler başarısız oldu
    logger.error(f"Docker işlemi {max_retries} denemeden sonra başarısız oldu: {str(last_exception)}")
    raise last_exception 