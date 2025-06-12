import os
import subprocess
import docker
import json
import re
import random
import datetime
import time

# Flask uygulamasını başlat ve şablon klasörünü doğru şekilde ayarla
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from werkzeug.utils import secure_filename

# Flask uygulamasını başlat ve şablon klasörünü doğru şekilde ayarla
template_dir = os.path.abspath('app/templates')
static_dir = os.path.abspath('app/static')
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.secret_key = "chronis_gizli_anahtar"  # Gerçek uygulamada değiştirin

# Global değişken olarak Docker istemcisini tanımla
client = None
cli_client = None

# Docker CLI tabanlı alternatif istemci
class DockerCLIClient:
    def __init__(self):
        # Docker CLI'ın varlığını kontrol et
        try:
            output = subprocess.check_output(['docker', 'version', '--format', '{{json .}}'])
            self.available = True
            print("Docker CLI erişimi başarılı")
        except Exception as e:
            self.available = False
            print(f"Docker CLI erişimi başarısız: {e}")
    
    def version(self):
        """Docker versiyonunu al"""
        try:
            output = subprocess.check_output(['docker', 'version', '--format', '{{json .}}'])
            return json.loads(output)
        except Exception as e:
            print(f"Versiyon alınamadı: {e}")
            return {"Version": "bilinmiyor", "ApiVersion": "bilinmiyor"}
    
    def containers_list(self, all=False):
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
            print(f"Container listesi alınamadı: {e}")
            return []
    
    def images_list(self):
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
            print(f"Image listesi alınamadı: {e}")
            return []
    
    def networks_list(self):
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
            print(f"Network listesi alınamadı: {e}")
            return []
    
    def volumes_list(self):
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
                        'mountpoint': mountpoint,
                        'attrs': {
                            'Name': volume_data.get('Name', ''),
                            'Driver': volume_data.get('Driver', ''),
                            'Mountpoint': mountpoint
                        }
                    })
                    volumes.append(volume)
            
            return volumes
        except Exception as e:
            print(f"Volume listesi alınamadı: {e}")
            return []
    
    def get_container(self, container_id):
        """Container detaylarını al"""
        try:
            cmd = ['docker', 'inspect', container_id]
            output = subprocess.check_output(cmd, universal_newlines=True)
            data = json.loads(output)[0]
            
            # Durum bilgisini standardize et
            status = data.get('State', {}).get('Status', '').lower()
            if 'running' in status:
                status_normalized = 'running'
            elif 'exited' in status:
                status_normalized = 'exited'
            else:
                status_normalized = status
            
            # Container ismini düzelt
            name = data.get('Name', '').lstrip('/')
            
            # Image bilgisini al
            image_tags = []
            image_name = data.get('Config', {}).get('Image', '')
            if image_name:
                image_tags.append(image_name)
            
            # Port bilgilerini al
            ports = []
            ports_data = data.get('NetworkSettings', {}).get('Ports', {})
            if ports_data:
                for container_port, host_ports in ports_data.items():
                    if host_ports:
                        for binding in host_ports:
                            ports.append(f"{binding.get('HostIp', '')}:{binding.get('HostPort', '')} -> {container_port}")
                    else:
                        ports.append(container_port)
            
            # Network bilgilerini al
            networks = data.get('NetworkSettings', {}).get('Networks', {})
            ip_address = "-"
            if networks:
                for net_name, net_data in networks.items():
                    ip_address = net_data.get('IPAddress', '-')
                    if ip_address and ip_address != '-':
                        break
            
            # Çevre değişkenlerini al
            env = data.get('Config', {}).get('Env', [])
            
            # Komut bilgisini al
            command = data.get('Config', {}).get('Cmd', [])
            if isinstance(command, list):
                command = ' '.join(command)
            
            container = type('obj', (object,), {
                'id': data.get('Id', ''),
                'short_id': data.get('Id', '')[:12],
                'name': name,
                'image': type('obj', (object,), {
                    'tags': image_tags
                }),
                'status': status_normalized,
                'command': command,
                'created': data.get('Created', '').split('T')[0] if 'T' in data.get('Created', '') else data.get('Created', ''),
                'ports': ports,
                'env': env,
                'attrs': {
                    'Created': data.get('Created', ''),
                    'State': data.get('State', {}),
                    'Config': data.get('Config', {}),
                    'NetworkSettings': {
                        'Networks': networks
                    }
                }
            })
            
            return container
        except Exception as e:
            print(f"Container detayları alınamadı: {e}")
            raise Exception(f"Container bulunamadı: {e}")
    
    def container_start(self, container_id):
        """Container'ı başlat"""
        try:
            subprocess.check_call(['docker', 'start', container_id])
            return True
        except Exception as e:
            print(f"Container başlatılamadı: {e}")
            raise Exception(f"Container başlatılamadı: {e}")
    
    def container_stop(self, container_id):
        """Container'ı durdur"""
        try:
            subprocess.check_call(['docker', 'stop', container_id])
            return True
        except Exception as e:
            print(f"Container durdurulamadı: {e}")
            raise Exception(f"Container durdurulamadı: {e}")
    
    def container_restart(self, container_id):
        """Container'ı yeniden başlat"""
        try:
            subprocess.check_call(['docker', 'restart', container_id])
            return True
        except Exception as e:
            print(f"Container yeniden başlatılamadı: {e}")
            raise Exception(f"Container yeniden başlatılamadı: {e}")
    
    def container_remove(self, container_id, force=False):
        """Container'ı sil"""
        try:
            cmd = ['docker', 'rm', container_id]
            if force:
                cmd.append('-f')
            subprocess.check_call(cmd)
            return True
        except Exception as e:
            print(f"Container silinemedi: {e}")
            raise Exception(f"Container silinemedi: {e}")
    
    def container_logs(self, container_id, tail=100):
        """Container loglarını al"""
        try:
            cmd = ['docker', 'logs', '--tail', str(tail), container_id]
            logs = subprocess.check_output(cmd, universal_newlines=True)
            return logs
        except Exception as e:
            print(f"Container logları alınamadı: {e}")
            raise Exception(f"Container logları alınamadı: {e}")

# Docker bağlantısını birkaç kez deneme
def connect_to_docker(max_attempts=5, delay=2):
    global client, cli_client
    
    # Önce CLI istemcisini başlat
    cli_client = DockerCLIClient()
    
    for attempt in range(max_attempts):
        try:
            # Docker socket yolları
            possible_paths = [
                '/var/run/docker.sock',
                '/run/docker.sock',
                '/tmp/docker.sock'
            ]
            
            # Docker host ortam değişkeni - burada direkt unix:// protokolü ile socket'i tanımlıyoruz
            # DOCKER_HOST değişkeni kullanmak yerine doğrudan socket'e bağlanma yaklaşımı
            for socket_path in possible_paths:
                if os.path.exists(socket_path):
                    print(f"Socket yolu bulundu: {socket_path}")
                    try:
                        # Direkt socket yolunu kullanarak bağlan
                        client = docker.DockerClient(base_url=f"unix://{socket_path}")
                        # Bağlantıyı test et
                        version = client.version()
                        print(f"Bağlantı başarılı. Docker versiyonu: {version.get('Version', 'bilinmiyor')}")
                        return True
                    except Exception as e:
                        print(f"Socket yolu {socket_path} üzerinden bağlantı başarısız: {e}")
                        continue
            
            # Alternatif olarak from_env kullanarak dene
            try:
                print("docker.from_env() ile bağlanmayı deniyorum...")
                client = docker.from_env()
                version = client.version()
                print(f"from_env ile bağlantı başarılı. Docker versiyonu: {version.get('Version', 'bilinmiyor')}")
                return True
            except Exception as e:
                print(f"from_env ile bağlantı başarısız: {e}")
            
            # Docker CLI bağlantısını kontrol et
            if cli_client.available:
                print("Docker CLI bağlantısı kullanılacak")
                # Python istemcisi başarısız olsa da CLI istemcisi kullanılabilir
            else:
                print("Docker CLI erişimi başarısız")
            
            print(f"Deneme {attempt+1}/{max_attempts} başarısız, {delay} saniye bekleyip tekrar deneniyor...")
            time.sleep(delay)
        
        except Exception as e:
            print(f"Deneme {attempt+1}/{max_attempts} sırasında hata: {e}")
            time.sleep(delay)
    
    if cli_client.available:
        print("Docker Python istemcisi başarısız, CLI istemcisi ile devam ediliyor.")
        return True
    else:
        print("Docker bağlantısı kurulamadı. Sınırlı işlevsellikle devam ediliyor.")
        return False

# Uygulama başlangıcında Docker'a bağlan
connect_to_docker()

@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    # Varsayılan boş stats nesnesi oluştur
    stats = {
        'containers': {
            'total': 0,
            'running': 0,
            'stopped': 0
        },
        'images': 0,
        'volumes': 0,
        'networks': 0
    }
    
    try:
        if client:
            # Docker API ile istatistikleri al
            containers = client.containers.list(all=True)
            running_containers = [c for c in containers if c.status == 'running']
            images = client.images.list()
            volumes = client.volumes.list()
            networks = client.networks.list()
            
            stats = {
                'containers': {
                    'total': len(containers),
                    'running': len(running_containers),
                    'stopped': len(containers) - len(running_containers)
                },
                'images': len(images),
                'volumes': len(volumes),
                'networks': len(networks)
            }
        elif cli_client and cli_client.available:
            # CLI ile istatistikleri al
            containers = cli_client.containers_list(all=True)
            running_containers = [c for c in containers if c.status == 'running']
            images = cli_client.images_list()
            volumes = cli_client.volumes_list()
            networks = cli_client.networks_list()
            
            stats = {
                'containers': {
                    'total': len(containers),
                    'running': len(running_containers),
                    'stopped': len(containers) - len(running_containers)
                },
                'images': len(images),
                'volumes': len(volumes),
                'networks': len(networks)
            }
        else:
            flash("Docker bağlantısı kurulamadı. Mock veri gösteriliyor.", "error")
        
        return render_template('dashboard.html', stats=stats)
    except Exception as e:
        flash(f"Docker bilgileri alınamadı: {e}", "error")
        return render_template('dashboard.html', stats=stats, error=str(e))

@app.route('/containers')
def container_list():
    try:
        if client:
            containers = client.containers.list(all=True)
        elif cli_client and cli_client.available:
            containers = cli_client.containers_list(all=True)
        else:
            containers = []
            flash("Docker bağlantısı kurulamadı.", "error")
            
        return render_template('containers.html', containers=containers)
    except Exception as e:
        flash(f"Container listesi alınamadı: {e}", "error")
        return render_template('containers.html', error=str(e))

@app.route('/containers/<id>')
def container_detail(id):
    try:
        if client:
            container = client.containers.get(id)
        elif cli_client and cli_client.available:
            container = cli_client.get_container(id)
        else:
            flash("Docker bağlantısı kurulamadı.", "error")
            return redirect(url_for('container_list'))
            
        return render_template('container_detail.html', container=container)
    except Exception as e:
        flash(f"Container detayları alınamadı: {e}", "error")
        return redirect(url_for('container_list'))

@app.route('/containers/start/<id>', methods=['POST'])
def start_container(id):
    try:
        if client:
            container = client.containers.get(id)
            container.start()
        elif cli_client and cli_client.available:
            cli_client.container_start(id)
        else:
            flash("Docker bağlantısı kurulamadı.", "error")
            return redirect(url_for('container_list'))
            
        flash(f"Container başlatıldı", "success")
    except Exception as e:
        flash(f"Container başlatılamadı: {e}", "error")
    return redirect(url_for('container_list'))

@app.route('/containers/stop/<id>', methods=['POST'])
def stop_container(id):
    try:
        if client:
            container = client.containers.get(id)
            container.stop()
        elif cli_client and cli_client.available:
            cli_client.container_stop(id)
        else:
            flash("Docker bağlantısı kurulamadı.", "error")
            return redirect(url_for('container_list'))
            
        flash(f"Container durduruldu", "success")
    except Exception as e:
        flash(f"Container durdurulamadı: {e}", "error")
    return redirect(url_for('container_list'))

@app.route('/containers/restart/<id>', methods=['POST'])
def restart_container(id):
    try:
        if client:
            container = client.containers.get(id)
            container.restart()
        elif cli_client and cli_client.available:
            cli_client.container_restart(id)
        else:
            flash("Docker bağlantısı kurulamadı.", "error")
            return redirect(url_for('container_list'))
            
        flash(f"Container yeniden başlatıldı", "success")
    except Exception as e:
        flash(f"Container yeniden başlatılamadı: {e}", "error")
    return redirect(url_for('container_list'))

@app.route('/containers/remove/<id>', methods=['POST'])
def remove_container(id):
    try:
        if client:
            container = client.containers.get(id)
            container.remove(force=True)
        elif cli_client and cli_client.available:
            cli_client.container_remove(id, force=True)
        else:
            flash("Docker bağlantısı kurulamadı.", "error")
            return redirect(url_for('container_list'))
            
        flash(f"Container silindi", "success")
    except Exception as e:
        flash(f"Container silinemedi: {e}", "error")
    return redirect(url_for('container_list'))

@app.route('/containers/logs/<id>')
def container_logs(id):
    try:
        if client:
            container = client.containers.get(id)
            logs = container.logs(tail=100).decode('utf-8')
        elif cli_client and cli_client.available:
            container = cli_client.get_container(id)
            logs = cli_client.container_logs(id, tail=100)
        else:
            flash("Docker bağlantısı kurulamadı.", "error")
            return redirect(url_for('container_list'))
            
        return render_template('container_logs.html', container=container, logs=logs)
    except Exception as e:
        flash(f"Container logları alınamadı: {e}", "error")
        return redirect(url_for('container_detail', id=id))

@app.route('/images')
def image_list():
    try:
        if client:
            images = client.images.list()
        elif cli_client and cli_client.available:
            images = cli_client.images_list()
        else:
            images = []
            flash("Docker bağlantısı kurulamadı.", "error")
            
        return render_template('images.html', images=images)
    except Exception as e:
        flash(f"Image listesi alınamadı: {e}", "error")
        return render_template('images.html', error=str(e))

@app.route('/networks')
def network_list():
    try:
        if client:
            networks = client.networks.list()
        elif cli_client and cli_client.available:
            networks = cli_client.networks_list()
        else:
            networks = []
            flash("Docker bağlantısı kurulamadı.", "error")
            
        return render_template('networks.html', networks=networks)
    except Exception as e:
        flash(f"Network listesi alınamadı: {e}", "error")
        return render_template('networks.html', error=str(e))

@app.route('/volumes')
def volume_list():
    try:
        if client:
            volumes = client.volumes.list()
        elif cli_client and cli_client.available:
            volumes = cli_client.volumes_list()
        else:
            volumes = []
            flash("Docker bağlantısı kurulamadı.", "error")
            
        return render_template('volumes.html', volumes=volumes)
    except Exception as e:
        flash(f"Volume listesi alınamadı: {e}", "error")
        return render_template('volumes.html', error=str(e))

@app.route('/api/stats')
def api_stats():
    try:
        stats = {
            'containers': {
                'total': 0,
                'running': 0,
                'stopped': 0
            },
            'images': 0,
            'volumes': 0,
            'networks': 0,
            'system': {
                'cpu_usage': random.randint(10, 60),
                'memory_usage': random.randint(20, 70),
                'disk_usage': random.randint(30, 80)
            },
            'events': [
                {
                    'time': datetime.datetime.now().strftime('%H:%M:%S'),
                    'event': 'Container başlatıldı',
                    'source': 'chronis',
                    'status': 'success'
                },
                {
                    'time': (datetime.datetime.now() - datetime.timedelta(minutes=2)).strftime('%H:%M:%S'),
                    'event': 'Image indirildi',
                    'source': 'nginx:latest',
                    'status': 'success'
                },
                {
                    'time': (datetime.datetime.now() - datetime.timedelta(minutes=5)).strftime('%H:%M:%S'),
                    'event': 'Container oluşturuldu',
                    'source': 'chronis',
                    'status': 'success'
                }
            ]
        }
        
        if client:
            containers = client.containers.list(all=True)
            running_containers = [c for c in containers if c.status == 'running']
            images = client.images.list()
            volumes = client.volumes.list()
            networks = client.networks.list()
            
            stats.update({
                'containers': {
                    'total': len(containers),
                    'running': len(running_containers),
                    'stopped': len(containers) - len(running_containers)
                },
                'images': len(images),
                'volumes': len(volumes),
                'networks': len(networks)
            })
        elif cli_client and cli_client.available:
            containers = cli_client.containers_list(all=True)
            running_containers = [c for c in containers if c.status == 'running']
            images = cli_client.images_list()
            volumes = cli_client.volumes_list()
            networks = cli_client.networks_list()
            
            stats.update({
                'containers': {
                    'total': len(containers),
                    'running': len(running_containers),
                    'stopped': len(containers) - len(running_containers)
                },
                'images': len(images),
                'volumes': len(volumes),
                'networks': len(networks)
            })
        
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/status')
def api_status():
    """Docker bağlantı durumunu kontrol et"""
    try:
        if client:
            version = client.version()
            return jsonify({
                'status': 'connected',
                'client': 'api',
                'version': version.get('Version', 'bilinmiyor'),
                'api_version': version.get('ApiVersion', 'bilinmiyor')
            })
        elif cli_client and cli_client.available:
            version = cli_client.version()
            return jsonify({
                'status': 'connected',
                'client': 'cli',
                'version': version.get('Server', {}).get('Version', 'bilinmiyor'),
                'api_version': version.get('Server', {}).get('ApiVersion', 'bilinmiyor')
            })
        else:
            return jsonify({'status': 'disconnected', 'error': 'Docker bağlantısı kurulamadı'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000) 