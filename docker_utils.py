import docker
import os
import logging
import time
import subprocess
import json
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
    
    # CLI tabanlı yedek Docker istemcisi
    try:
        client = DockerCLIClient()
        if client.available:
            logger.info("Docker CLI bağlantısı başarılı")
            return client
        else:
            raise Exception("Docker CLI bağlantısı başarısız")
    except Exception as e:
        last_exception = e
        logger.warning(f"Docker CLI bağlantısı başarısız: {str(e)}")
    
    # Hiçbir bağlantı çalışmadıysa son hatayı yükselt
    raise Exception(f"Docker'a bağlanılamıyor. Son hata: {str(last_exception)}")

# Docker CLI tabanlı alternatif istemci
class DockerCLIClient:
    def __init__(self):
        # Docker CLI'ın varlığını kontrol et
        try:
            output = subprocess.check_output(['docker', 'version', '--format', '{{json .}}'])
            self.available = True
            logger.info("Docker CLI erişimi başarılı")
        except Exception as e:
            self.available = False
            logger.error(f"Docker CLI erişimi başarısız: {e}")
    
    def ping(self):
        """Docker bağlantısını test et"""
        try:
            subprocess.check_output(['docker', 'info'], stderr=subprocess.PIPE)
            return True
        except:
            return False
    
    def containers(self):
        """SDK uyumluluğu için containers nesnesi"""
        return DockerCLIContainers()
    
    def images(self):
        """SDK uyumluluğu için images nesnesi"""
        return DockerCLIImages()
    
    def networks(self):
        """SDK uyumluluğu için networks nesnesi"""
        return DockerCLINetworks()
    
    def volumes(self):
        """SDK uyumluluğu için volumes nesnesi"""
        return DockerCLIVolumes()

class DockerCLIContainers:
    def list(self, all=False):
        """Container listesini al"""
        try:
            cmd = ['docker', 'ps', '--format', '{{json .}}']
            if all:
                cmd.append('-a')
            
            output = subprocess.check_output(cmd, universal_newlines=True)
            containers = []
            
            # Her satırı ayrı bir JSON olarak işle
            for line in output.strip().split('\n'):
                if line:
                    container_data = json.loads(line)
                    
                    # IP adresi için network bilgisini al
                    ip_address = "-"
                    if container_data.get('ID'):
                        try:
                            inspect_cmd = ['docker', 'inspect', container_data.get('ID')]
                            inspect_output = subprocess.check_output(inspect_cmd, universal_newlines=True)
                            inspect_data = json.loads(inspect_output)[0]
                            networks = inspect_data.get('NetworkSettings', {}).get('Networks', {})
                            if networks:
                                for net_name, net_data in networks.items():
                                    ip_address = net_data.get('IPAddress', '-')
                                    if ip_address and ip_address != '-':
                                        break
                        except:
                            pass
                    
                    # Status değerini running/exited formatına dönüştür
                    status = container_data.get('Status', '').lower()
                    if 'up' in status:
                        status_normalized = 'running'
                    elif 'exited' in status:
                        status_normalized = 'exited'
                    else:
                        status_normalized = status
                    
                    # Şablonlarla uyumlu container nesnesi oluştur
                    container = type('obj', (object,), {
                        'id': container_data.get('ID', ''),
                        'name': container_data.get('Names', ''),
                        'image': type('obj', (object,), {
                            'tags': [container_data.get('Image', '')]
                        }),
                        'status': status_normalized,
                        'command': container_data.get('Command', ''),
                        'created': container_data.get('CreatedAt', ''),
                        'ports': container_data.get('Ports', ''),
                        'attrs': {
                            'Created': container_data.get('CreatedAt', ''),
                            'NetworkSettings': {
                                'Networks': {
                                    'default': {
                                        'IPAddress': ip_address
                                    }
                                }
                            }
                        }
                    })
                    containers.append(container)
            
            return containers
        except Exception as e:
            logger.error(f"Container listesi alınamadı: {e}")
            return []
    
    def get(self, container_id):
        """Belirli bir konteyneri al"""
        try:
            cmd = ['docker', 'inspect', container_id]
            output = subprocess.check_output(cmd, universal_newlines=True)
            data = json.loads(output)[0]
            
            # Status değerini running/exited formatına dönüştür
            status = data.get('State', {}).get('Status', '').lower()
            if status == 'running':
                status_normalized = 'running'
            elif status == 'exited':
                status_normalized = 'exited'
            else:
                status_normalized = status
            
            # Şablonlarla uyumlu container nesnesi oluştur
            container = type('obj', (object,), {
                'id': data.get('Id', ''),
                'name': data.get('Name', '').lstrip('/'),
                'image': type('obj', (object,), {
                    'tags': [data.get('Config', {}).get('Image', '')]
                }),
                'status': status_normalized,
                'attrs': data,
                'logs': lambda **kwargs: self._get_logs(container_id, **kwargs),
                'start': lambda: self._start_container(container_id),
                'stop': lambda: self._stop_container(container_id),
                'restart': lambda: self._restart_container(container_id),
                'remove': lambda **kwargs: self._remove_container(container_id, **kwargs),
                'exec_run': lambda **kwargs: self._exec_in_container(container_id, **kwargs)
            })
            return container
        except Exception as e:
            logger.error(f"Konteyner alınamadı {container_id}: {str(e)}")
            raise Exception(f"Konteyner bulunamadı: {container_id}")
    
    def _get_logs(self, container_id, tail=100):
        """Konteyner loglarını al"""
        try:
            cmd = ['docker', 'logs', '--tail', str(tail), container_id]
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, universal_newlines=True)
            return output
        except Exception as e:
            logger.error(f"Loglar alınamadı {container_id}: {str(e)}")
            return ""
    
    def _start_container(self, container_id):
        """Konteyneri başlat"""
        try:
            subprocess.check_output(['docker', 'start', container_id])
            return True
        except Exception as e:
            logger.error(f"Konteyner başlatılamadı {container_id}: {str(e)}")
            return False
    
    def _stop_container(self, container_id):
        """Konteyneri durdur"""
        try:
            subprocess.check_output(['docker', 'stop', container_id])
            return True
        except Exception as e:
            logger.error(f"Konteyner durdurulamadı {container_id}: {str(e)}")
            return False
    
    def _restart_container(self, container_id):
        """Konteyneri yeniden başlat"""
        try:
            subprocess.check_output(['docker', 'restart', container_id])
            return True
        except Exception as e:
            logger.error(f"Konteyner yeniden başlatılamadı {container_id}: {str(e)}")
            return False
    
    def _remove_container(self, container_id, force=False):
        """Konteyneri sil"""
        try:
            cmd = ['docker', 'rm', container_id]
            if force:
                cmd.insert(2, '-f')
            subprocess.check_output(cmd)
            return True
        except Exception as e:
            logger.error(f"Konteyner silinemedi {container_id}: {str(e)}")
            return False
    
    def _exec_in_container(self, container_id, cmd, stdout=True, stderr=True, **kwargs):
        """Konteyner içinde komut çalıştır"""
        try:
            if isinstance(cmd, list):
                cmd_str = ' '.join(cmd)
            else:
                cmd_str = cmd
            
            exec_cmd = ['docker', 'exec', container_id, 'sh', '-c', cmd_str]
            output = subprocess.check_output(exec_cmd, stderr=subprocess.STDOUT if stderr else None, universal_newlines=True)
            
            # SDK uyumlu çıktı nesnesi
            result = type('obj', (object,), {
                'exit_code': 0,
                'output': output.encode('utf-8')
            })
            return result
        except subprocess.CalledProcessError as e:
            # Hata durumunda SDK uyumlu çıktı nesnesi
            result = type('obj', (object,), {
                'exit_code': e.returncode,
                'output': e.output.encode('utf-8') if hasattr(e, 'output') else b''
            })
            return result
        except Exception as e:
            logger.error(f"Komut çalıştırılamadı {container_id}: {str(e)}")
            # Genel hata durumunda SDK uyumlu çıktı nesnesi
            result = type('obj', (object,), {
                'exit_code': 1,
                'output': str(e).encode('utf-8')
            })
            return result

class DockerCLIImages:
    def list(self):
        """Image listesini al"""
        try:
            cmd = ['docker', 'images', '--format', '{{json .}}']
            output = subprocess.check_output(cmd, universal_newlines=True)
            images = []
            
            for line in output.strip().split('\n'):
                if line:
                    image_data = json.loads(line)
                    
                    # Size değerini byte cinsinden al
                    size_str = image_data.get('Size', '0')
                    size_bytes = 0
                    if 'MB' in size_str:
                        size_bytes = float(size_str.replace('MB', '').strip()) * 1000000
                    elif 'GB' in size_str:
                        size_bytes = float(size_str.replace('GB', '').strip()) * 1000000000
                    elif 'kB' in size_str:
                        size_bytes = float(size_str.replace('kB', '').strip()) * 1000
                    
                    tag = image_data.get('Repository', '') + ':' + image_data.get('Tag', '')
                    if tag == ':':
                        tag = '<none>:<none>'
                    
                    # Şablonlarla uyumlu image nesnesi oluştur
                    image = type('obj', (object,), {
                        'id': image_data.get('ID', ''),
                        'short_id': image_data.get('ID', '')[:12],
                        'tags': [tag] if tag != '<none>:<none>' else [],
                        'created': image_data.get('CreatedAt', ''),
                        'attrs': {
                            'Size': size_bytes,
                            'Created': image_data.get('CreatedAt', '')
                        }
                    })
                    images.append(image)
            
            return images
        except Exception as e:
            logger.error(f"Image listesi alınamadı: {e}")
            return []

class DockerCLINetworks:
    def list(self):
        """Network listesini al"""
        try:
            cmd = ['docker', 'network', 'ls', '--format', '{{json .}}']
            output = subprocess.check_output(cmd, universal_newlines=True)
            networks = []
            
            for line in output.strip().split('\n'):
                if line:
                    network_data = json.loads(line)
                    
                    # Şablonlarla uyumlu network nesnesi oluştur
                    network = type('obj', (object,), {
                        'id': network_data.get('ID', ''),
                        'name': network_data.get('Name', ''),
                        'driver': network_data.get('Driver', ''),
                        'scope': network_data.get('Scope', ''),
                        'attrs': {
                            'Name': network_data.get('Name', ''),
                            'Driver': network_data.get('Driver', ''),
                            'Scope': network_data.get('Scope', '')
                        }
                    })
                    networks.append(network)
            
            return networks
        except Exception as e:
            logger.error(f"Network listesi alınamadı: {e}")
            return []

class DockerCLIVolumes:
    def list(self):
        """Volume listesini al"""
        try:
            cmd = ['docker', 'volume', 'ls', '--format', '{{json .}}']
            output = subprocess.check_output(cmd, universal_newlines=True)
            volumes = []
            
            for line in output.strip().split('\n'):
                if line:
                    volume_data = json.loads(line)
                    
                    # Volume için ek bilgi alma
                    inspect_cmd = ['docker', 'volume', 'inspect', volume_data.get('Name', '')]
                    try:
                        inspect_output = subprocess.check_output(inspect_cmd, universal_newlines=True)
                        inspect_data = json.loads(inspect_output)[0]
                        mountpoint = inspect_data.get('Mountpoint', '')
                    except:
                        mountpoint = ''
                    
                    # Şablonlarla uyumlu volume nesnesi oluştur
                    volume = type('obj', (object,), {
                        'name': volume_data.get('Name', ''),
                        'driver': volume_data.get('Driver', ''),
                        'attrs': {
                            'Name': volume_data.get('Name', ''),
                            'Driver': volume_data.get('Driver', ''),
                            'Mountpoint': mountpoint
                        }
                    })
                    volumes.append(volume)
            
            return volumes
        except Exception as e:
            logger.error(f"Volume listesi alınamadı: {e}")
            return []

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