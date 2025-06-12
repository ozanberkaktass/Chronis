import os
import subprocess
import docker
import json
import re
import random
import datetime
import time
import pty
import fcntl
import struct
import termios
import signal
import uuid
import threading
from functools import wraps

# Flask uygulamasını başlat ve şablon klasörünü doğru şekilde ayarla
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, session
from flask_socketio import SocketIO, emit, disconnect
from werkzeug.utils import secure_filename

# Flask uygulamasını başlat ve şablon klasörünü doğru şekilde ayarla
template_dir = os.path.abspath('app/templates')
static_dir = os.path.abspath('app/static')
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.secret_key = "chronis_gizli_anahtar"  # Gerçek uygulamada değiştirin

# Socket.IO
socketio = SocketIO(app, cors_allowed_origins="*")

# Global değişken olarak Docker istemcisini tanımla
client = None
cli_client = None

# Terminal oturumları için kaydı tutacak dictionary
terminal_sessions = {}
active_terminals = {}
recording_sessions = {}

# Oturum kayıtları için klasör
RECORDINGS_DIR = os.path.join(static_dir, 'recordings')
os.makedirs(RECORDINGS_DIR, exist_ok=True)

# Yetkilendirme kontrolü için dekoratör
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin'):
            flash('Bu sayfayı görüntülemek için yönetici hakları gereklidir.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

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
def connect_to_docker(max_attempts=1, delay=1):
    global client, cli_client
    
    try:
        # Önce CLI istemcisini başlat
        cli_client = DockerCLIClient()
        
        # Docker CLI bağlantısını kontrol et
        if cli_client.available:
            print("Docker CLI bağlantısı kullanılacak")
            return True
        else:
            print("Docker CLI erişimi başarısız, sınırlı işlevsellikle devam ediliyor.")
            return False
    except Exception as e:
        print(f"Docker bağlantısı sırasında hata: {e}")
        return False

# Uygulama başlangıcında Docker'a bağlan
connect_to_docker()

# Terminal işlemleri
def create_terminal(fd, pid):
    """Terminal verilerini işle ve sockete gönder"""
    def read_and_forward_terminal_output():
        max_read_bytes = 1024 * 20
        while True:
            try:
                data = os.read(fd, max_read_bytes)
                socketio.emit('data', data.decode(), namespace='/terminal', room=request.sid)
                
                # Kayıt yapılıyorsa verileri kaydet
                if request.sid in recording_sessions and recording_sessions[request.sid]['recording']:
                    recording_sessions[request.sid]['data'].append({
                        'type': 'output',
                        'data': data.decode(),
                        'time': datetime.datetime.now().isoformat()
                    })
            except (OSError, IOError):
                break
    
    # Arka planda terminal çıktısını oku
    thread = threading.Thread(target=read_and_forward_terminal_output)
    thread.daemon = True
    thread.start()
    
    return thread

def get_terminal_size(fd):
    """Terminal boyutunu al"""
    size = struct.pack('HHHH', 0, 0, 0, 0)
    size = fcntl.ioctl(fd, termios.TIOCGWINSZ, size)
    rows, cols, _, _ = struct.unpack('HHHH', size)
    return rows, cols

def set_terminal_size(fd, rows, cols):
    """Terminal boyutunu ayarla"""
    size = struct.pack('HHHH', rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, size)

# Socket.IO terminal olayları
@socketio.on('connect', namespace='/terminal')
def connect():
    """Yeni bağlantı"""
    pass

@socketio.on('disconnect', namespace='/terminal')
def disconnect_terminal():
    """Bağlantı kesildiğinde"""
    if request.sid in active_terminals:
        # Terminal prosesini sonlandır
        if active_terminals[request.sid]['pid']:
            try:
                os.kill(active_terminals[request.sid]['pid'], signal.SIGTERM)
            except OSError:
                pass
            
        # Kayıt yapılıyorsa oturumu kaydet
        if request.sid in recording_sessions and recording_sessions[request.sid]['recording']:
            save_recording(request.sid)
        
        # Active terminal listesinden çıkar
        del active_terminals[request.sid]
    
    # Kayıt durumunu temizle
    if request.sid in recording_sessions:
        del recording_sessions[request.sid]

@socketio.on('start', namespace='/terminal')
def start_terminal(data):
    """Terminal oturumu başlat"""
    connection_type = data.get('type')
    
    if connection_type == 'container':
        # Container'da terminal başlat
        container_id = data.get('containerId')
        cmd = data.get('cmd', '/bin/bash')
        
        # Container çalışıyor mu kontrol et
        try:
            container = client.containers.get(container_id)
            if container.status != 'running':
                emit('error', 'Container çalışmıyor.')
                return
        except Exception as e:
            emit('error', f'Container bulunamadı: {str(e)}')
            return
        
        # Exec oluştur ve başlat
        try:
            # PTY açılımı
            master_fd, slave_fd = pty.openpty()
            
            # Docker exec komutu
            exec_command = f"docker exec -it {container_id} {cmd}"
            process = subprocess.Popen(
                exec_command,
                shell=True,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True
            )
            
            # Terminal boyutunu ayarla
            set_terminal_size(master_fd, data.get('rows', 24), data.get('cols', 80))
            
            # Aktif terminaller listesine ekle
            active_terminals[request.sid] = {
                'fd': master_fd,
                'pid': process.pid,
                'type': 'container',
                'target': container_id,
                'start_time': datetime.datetime.now()
            }
            
            # Terminal verilerini okuma ve yönlendirme
            create_terminal(master_fd, process.pid)
            
            # Kayıt başlat
            if data.get('record', False):
                recording_sessions[request.sid] = {
                    'recording': True,
                    'data': [],
                    'type': 'container',
                    'target': container_id,
                    'start_time': datetime.datetime.now()
                }
            
        except Exception as e:
            emit('error', f'Terminal başlatılamadı: {str(e)}')
            return
    
    elif connection_type == 'host':
        # Host sistemde terminal başlat
        try:
            # Kullanıcının yetki kontrolü
            if not session.get('admin'):
                emit('error', 'Host terminal erişimi için yönetici hakları gerekiyor.')
                return
            
            # PTY açılımı
            master_fd, slave_fd = pty.openpty()
            
            # Shell başlat
            process = subprocess.Popen(
                ['/bin/bash'],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True
            )
            
            # Terminal boyutunu ayarla
            set_terminal_size(master_fd, data.get('rows', 24), data.get('cols', 80))
            
            # Aktif terminaller listesine ekle
            active_terminals[request.sid] = {
                'fd': master_fd,
                'pid': process.pid,
                'type': 'host',
                'target': 'host',
                'start_time': datetime.datetime.now()
            }
            
            # Terminal verilerini okuma ve yönlendirme
            create_terminal(master_fd, process.pid)
            
            # Kayıt başlat
            if data.get('record', False):
                recording_sessions[request.sid] = {
                    'recording': True,
                    'data': [],
                    'type': 'host',
                    'target': 'Host',
                    'start_time': datetime.datetime.now()
                }
            
        except Exception as e:
            emit('error', f'Host terminal başlatılamadı: {str(e)}')
            return
    
    elif connection_type == 'ssh':
        # SSH bağlantısı başlat
        try:
            # SSH bilgilerini al
            host = data.get('host')
            port = data.get('port', 22)
            username = data.get('username')
            auth_type = data.get('authType')
            
            # Kimlik doğrulama için parametreler
            ssh_command = f"ssh {username}@{host} -p {port}"
            
            if auth_type == 'key':
                # SSH anahtarı kullanımı için
                key_content = data.get('key', '')
                
                # Geçici anahtar dosyası oluştur
                key_file = os.path.join(RECORDINGS_DIR, f"temp_key_{uuid.uuid4().hex}")
                with open(key_file, 'w') as f:
                    f.write(key_content)
                os.chmod(key_file, 0o600)  # Dosya izinlerini ayarla
                
                ssh_command += f" -i {key_file}"
            
            # PTY açılımı
            master_fd, slave_fd = pty.openpty()
            
            # SSH komutu başlat
            process = subprocess.Popen(
                ssh_command,
                shell=True,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True
            )
            
            # Terminal boyutunu ayarla
            set_terminal_size(master_fd, data.get('rows', 24), data.get('cols', 80))
            
            # Aktif terminaller listesine ekle
            active_terminals[request.sid] = {
                'fd': master_fd,
                'pid': process.pid,
                'type': 'ssh',
                'target': f"{username}@{host}:{port}",
                'key_file': key_file if auth_type == 'key' else None,
                'start_time': datetime.datetime.now()
            }
            
            # Terminal verilerini okuma ve yönlendirme
            create_terminal(master_fd, process.pid)
            
            # Kayıt başlat
            if data.get('record', False):
                recording_sessions[request.sid] = {
                    'recording': True,
                    'data': [],
                    'type': 'ssh',
                    'target': f"{username}@{host}",
                    'start_time': datetime.datetime.now()
                }
            
        except Exception as e:
            emit('error', f'SSH bağlantısı başlatılamadı: {str(e)}')
            return
    
    else:
        emit('error', 'Geçersiz bağlantı tipi.')

@socketio.on('data', namespace='/terminal')
def handle_terminal_input(data):
    """Terminal girdisi al ve işle"""
    if request.sid in active_terminals:
        fd = active_terminals[request.sid]['fd']
        try:
            os.write(fd, data.encode())
            
            # Kayıt yapılıyorsa verileri kaydet
            if request.sid in recording_sessions and recording_sessions[request.sid]['recording']:
                recording_sessions[request.sid]['data'].append({
                    'type': 'input',
                    'data': data,
                    'time': datetime.datetime.now().isoformat()
                })
                
        except (OSError, IOError) as e:
            emit('error', f'Veri yazılırken hata oluştu: {str(e)}')

@socketio.on('resize', namespace='/terminal')
def resize_terminal(data):
    """Terminal boyutunu değiştir"""
    if request.sid in active_terminals:
        fd = active_terminals[request.sid]['fd']
        try:
            set_terminal_size(fd, data.get('rows', 24), data.get('cols', 80))
        except (OSError, IOError) as e:
            emit('error', f'Terminal boyutu değiştirilirken hata oluştu: {str(e)}')

@socketio.on('toggleRecord', namespace='/terminal')
def toggle_recording(data):
    """Terminal kaydını başlat/durdur"""
    recording = data.get('recording', False)
    
    if request.sid in active_terminals:
        # Kayıt var mı kontrol et
        if request.sid not in recording_sessions:
            # Yeni kayıt oluştur
            recording_sessions[request.sid] = {
                'recording': recording,
                'data': [],
                'type': active_terminals[request.sid]['type'],
                'target': active_terminals[request.sid]['target'],
                'start_time': datetime.datetime.now()
            }
        else:
            # Mevcut kaydı güncelle
            if recording and not recording_sessions[request.sid]['recording']:
                # Kaydı başlat
                recording_sessions[request.sid]['recording'] = True
            elif not recording and recording_sessions[request.sid]['recording']:
                # Kaydı durdur ve kaydet
                recording_sessions[request.sid]['recording'] = False
                save_recording(request.sid)

def save_recording(sid):
    """Terminal kaydını kaydet"""
    if sid in recording_sessions:
        recording = recording_sessions[sid]
        recording_id = uuid.uuid4().hex
        
        # Kayıt meta verisi
        metadata = {
            'id': recording_id,
            'type': recording['type'],
            'target': recording['target'],
            'start_time': recording['start_time'].isoformat(),
            'end_time': datetime.datetime.now().isoformat(),
            'user': session.get('username', 'anonymous')
        }
        
        # Kayıt verisi
        recording_data = {
            'metadata': metadata,
            'events': recording['data']
        }
        
        # Kayıt dosyasını oluştur
        recording_file = os.path.join(RECORDINGS_DIR, f"{recording_id}.json")
        with open(recording_file, 'w') as f:
            json.dump(recording_data, f)
        
        # Terminal oturumları listesine ekle
        terminal_sessions[recording_id] = metadata
        
        return recording_id
    
    return None

# Terminal sayfası
@app.route('/terminal')
def terminal():
    """Terminal sayfasını görüntüle"""
    return render_template('terminal.html', title='Terminal')

# Çalışan containerları getir (terminal için)
@app.route('/api/containers/running')
def get_running_containers():
    """Çalışan container listesini getir"""
    try:
        if client:
            containers = client.containers.list(filters={"status": "running"})
            container_list = []
            
            for container in containers:
                container_list.append({
                    'id': container.id,
                    'name': container.name
                })
            
            return jsonify(container_list)
        elif cli_client and cli_client.available:
            containers = cli_client.containers_list(all=False)
            container_list = []
            
            for container in containers:
                if container.status == 'running':
                    container_list.append({
                        'id': container.id,
                        'name': container.name
                    })
            
            return jsonify(container_list)
        else:
            return jsonify([])
    except Exception as e:
        return jsonify([])

# Terminal oturumlarını getir
@app.route('/api/terminal/sessions')
def get_terminal_sessions():
    """Kayıtlı terminal oturumlarını getir"""
    sessions_list = []
    
    for recording_id, metadata in terminal_sessions.items():
        sessions_list.append(metadata)
    
    # Oturumları tarih sırasına göre sırala (en yeniden en eskiye)
    sessions_list.sort(key=lambda x: x['start_time'], reverse=True)
    
    return jsonify(sessions_list)

# Terminal kaydını getir
@app.route('/api/terminal/recordings/<recording_id>')
def get_terminal_recording(recording_id):
    """Terminal kaydını getir"""
    recording_file = os.path.join(RECORDINGS_DIR, f"{recording_id}.json")
    
    if os.path.exists(recording_file):
        with open(recording_file, 'r') as f:
            recording_data = json.load(f)
        return jsonify(recording_data)
    else:
        return jsonify({'error': 'Kayıt bulunamadı'}), 404

# Terminal kaydını sil
@app.route('/api/terminal/recordings/<recording_id>', methods=['DELETE'])
def delete_terminal_recording(recording_id):
    """Terminal kaydını sil"""
    recording_file = os.path.join(RECORDINGS_DIR, f"{recording_id}.json")
    
    if os.path.exists(recording_file):
        try:
            os.remove(recording_file)
            
            # Terminal oturumları listesinden kaldır
            if recording_id in terminal_sessions:
                del terminal_sessions[recording_id]
            
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': f'Kayıt silinirken hata oluştu: {str(e)}'}), 500
    else:
        return jsonify({'error': 'Kayıt bulunamadı'}), 404

# Ana fonksiyonlar
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
        # Şu anki sunucu saati
        now = datetime.datetime.now()
        # Türkiye saati için 3 saat ekliyoruz
        tr_now = now + datetime.timedelta(hours=3)
        
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
                'disk_usage': random.randint(30, 80),
                'time': tr_now.strftime('%H:%M:%S')
            },
            'events': [
                {
                    'time': tr_now.strftime('%H:%M:%S'),
                    'event': 'Container başlatıldı',
                    'source': 'chronis',
                    'status': 'success'
                },
                {
                    'time': (tr_now - datetime.timedelta(minutes=2)).strftime('%H:%M:%S'),
                    'event': 'Image indirildi',
                    'source': 'nginx:latest',
                    'status': 'success'
                },
                {
                    'time': (tr_now - datetime.timedelta(minutes=5)).strftime('%H:%M:%S'),
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

# Tarih biçimlendirme filtresi
@app.template_filter('format_date')
def format_date(value, format='%Y-%m-%d %H:%M'):
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            try:
                value = datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%f')
            except (ValueError, TypeError):
                return value
    return value.strftime(format)

if __name__ == "__main__":
    connect_to_docker()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True) 