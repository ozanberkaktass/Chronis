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
import eventlet
from functools import wraps
import traceback
import paramiko

# WebSocket için eventlet'i kullan
eventlet.monkey_patch()

# Flask uygulamasını başlat ve şablon klasörünü doğru şekilde ayarla
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, session
from flask_socketio import SocketIO, emit, disconnect
from werkzeug.utils import secure_filename

# Flask uygulamasını başlat ve şablon klasörünü doğru şekilde ayarla
template_dir = os.path.abspath('app/templates')
static_dir = os.path.abspath('app/static')
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.secret_key = "chronis_gizli_anahtar"  # Gerçek uygulamada değiştirin

# Flask ayarları
app.config['SESSION_TYPE'] = 'filesystem'
app.config['DEBUG'] = True
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Socket.IO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60, logger=True, engineio_logger=True)

# Global değişken olarak Docker istemcisini tanımla
docker_client = None

# Terminal oturumları
terminal_sessions = {}

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
    
    def volumes_list(self, all=False):
        """Volume listesini al"""
        try:
            cmd = ['docker', 'volume', 'ls', '--format', '{{json .}}']
            if all:
                cmd.append('-a')
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
def connect_to_docker(max_attempts=3, delay=1):
    global docker_client
    
    # Docker bağlantı hatalarını tutacak liste
    connection_errors = []
    
    for attempt in range(max_attempts):
        try:
            # Docker API istemcisini başlat - farklı bağlantı yöntemlerini dene
            try:
                # Önce varsayılan yöntemi dene
                docker_client = docker.from_env()
                # Bağlantıyı test et
                version = docker_client.version()
                print(f"Docker'a bağlandı: {version.get('Version', 'bilinmiyor')}")
                return True
            except Exception as env_error:
                connection_errors.append(f"Varsayılan bağlantı hatası: {str(env_error)}")
                # Unix soket yöntemi dene (Linux)
                try:
                    docker_client = docker.DockerClient(base_url='unix:///var/run/docker.sock')
                    version = docker_client.version()
                    print(f"Docker'a Unix soket ile bağlandı: {version.get('Version', 'bilinmiyor')}")
                    return True
                except Exception as unix_error:
                    connection_errors.append(f"Unix soket bağlantı hatası: {str(unix_error)}")
                    # Windows named pipe dene
                    try:
                        docker_client = docker.DockerClient(base_url='npipe:////./pipe/docker_engine')
                        version = docker_client.version()
                        print(f"Docker'a Windows pipe ile bağlandı: {version.get('Version', 'bilinmiyor')}")
                        return True
                    except Exception as win_error:
                        connection_errors.append(f"Windows pipe bağlantı hatası: {str(win_error)}")
                        # TCP ile dene
                        try:
                            docker_client = docker.DockerClient(base_url='tcp://localhost:2375')
                            version = docker_client.version()
                            print(f"Docker'a TCP ile bağlandı: {version.get('Version', 'bilinmiyor')}")
                            return True
                        except Exception as tcp_error:
                            connection_errors.append(f"TCP bağlantı hatası: {str(tcp_error)}")
                            raise Exception("Tüm Docker bağlantı yöntemleri başarısız oldu")
                
        except Exception as e:
            error_msg = f"Docker bağlantı hatası (deneme {attempt+1}/{max_attempts}): {str(e)}"
            print(error_msg)
            if attempt < max_attempts - 1:
                time.sleep(delay)
    
    # Hata detaylarını yazdır
    print("Docker bağlantı hataları detayları:")
    for i, error in enumerate(connection_errors):
        print(f"  {i+1}. {error}")
    
    print("Docker'a bağlanılamadı, uygulama sınırlı işlevsellikle çalışacak.")
    # Docker client değişkenini None olarak ayarla
    docker_client = None
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
def terminal_connect():
    print(f"Yeni terminal bağlantısı: {request.sid}")

@socketio.on('disconnect', namespace='/terminal')
def terminal_disconnect():
    print(f"Terminal bağlantısı kesildi: {request.sid}")
    # Mevcut oturumu kapat
    if request.sid in terminal_sessions:
        session_info = terminal_sessions.get(request.sid)
        close_terminal_session(session_info)
        terminal_sessions.pop(request.sid, None)

@socketio.on('create_session', namespace='/terminal')
def create_terminal_session(data):
    try:
        print(f"Terminal oturumu oluşturma isteği: {data}")
        session_id = str(uuid.uuid4())
        session_type = data.get('type')
        target = data.get('target')
        host = data.get('host')
        port = data.get('port')
        username = data.get('username')
        password = data.get('password')
        
        fd = None
        pid = None
        
        # Bağlantı tipine göre terminal başlat
        if session_type == 'container':
            if not docker_client:
                emit('connection_error', {'error': 'Docker bağlantısı yok'})
                return
            
            # Container ID veya adına göre konteyner bul
            container = None
            try:
                container = docker_client.containers.get(target)
            except Exception as e:
                emit('connection_error', {'error': f'Konteyner bulunamadı: {str(e)}'})
                return
            
            # Konteyner çalışıyor mu kontrol et
            if container.status != 'running':
                emit('connection_error', {'error': 'Konteyner çalışmıyor'})
                return
            
            # Konteyner exec oluştur
            exec_id = None
            try:
                exec_command = ['/bin/sh', '-c', 'if command -v bash >/dev/null 2>&1; then bash; else sh; fi']
                exec_result = container.exec_run(
                    exec_command,
                    tty=True,
                    stdin=True,
                    socket=True,
                    privileged=True,
                    user='root'
                )
                exec_id = exec_result.output
                
                # PTY oluştur
                fd, child_fd = pty.openpty()
                
                # Boyutu ayarla
                fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
                
                # Container exec ile bağlantı kur - burada tam implementasyon gerekiyor
                def read_from_container(client_sid, exec_socket):
                    try:
                        while True:
                            data = exec_socket.recv(1024).decode('utf-8', errors='ignore')
                            if not data:
                                break
                            socketio.emit('terminal_output', {'output': data}, namespace='/terminal', room=client_sid)
                    except Exception as e:
                        print(f"Konteyner veri okuma hatası: {str(e)}")
                        socketio.emit('connection_error', {'error': f'Okuma hatası: {str(e)}'}, 
                                     namespace='/terminal', room=client_sid)
                
                # İstemci kimliğini thread'e geçir
                thread = threading.Thread(
                    target=read_from_container, 
                    args=(request.sid, exec_id),
                    daemon=True
                )
                thread.start()
                
            except Exception as e:
                emit('connection_error', {'error': f'Exec oluşturma hatası: {str(e)}'})
                print(f"Konteyner exec hatası: {str(e)}")
                return
        
        elif session_type == 'host':
            # Yerel sistem için PTY oluştur
            try:
                if os.name == 'posix':
                    shell = os.environ.get('SHELL', '/bin/bash')
                    fd, child_fd = pty.openpty()
                    pid = os.fork()
                    
                    if pid == 0:  # Çocuk süreç
                        os.close(fd)
                        os.dup2(child_fd, 0)
                        os.dup2(child_fd, 1)
                        os.dup2(child_fd, 2)
                        os.close(child_fd)
                        
                        env = os.environ.copy()
                        env['TERM'] = 'xterm-256color'
                        
                        os.execvpe(shell, [shell], env)
                    else:  # Ana süreç
                        os.close(child_fd)
                        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
                else:
                    # Windows için terminal başlatma - subprocess kullanabilir
                    pass
            except Exception as e:
                emit('connection_error', {'error': f'PTY oluşturma hatası: {str(e)}'})
                print(f"PTY hatası: {str(e)}")
                return
        
        elif session_type == 'ssh':
            # SSH bağlantısı için paramiko kullan
            try:
                # SSH istemcisi oluştur
                ssh_client = paramiko.SSHClient()
                ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                # Bağlantı kur
                ssh_client.connect(
                    hostname=host,
                    port=int(port),
                    username=username,
                    password=password,
                    timeout=10
                )
                
                # PTY oluştur
                transport = ssh_client.get_transport()
                channel = transport.open_session()
                channel.get_pty(term='xterm-256color', width=80, height=24)
                channel.invoke_shell()
                
                # Terminali okuma işlevi
                def read_from_ssh(client_sid, ssh_channel):
                    try:
                        while True:
                            if ssh_channel.recv_ready():
                                data = ssh_channel.recv(1024).decode('utf-8', errors='ignore')
                                if not data:
                                    break
                                socketio.emit('terminal_output', {'output': data}, namespace='/terminal', room=client_sid)
                            time.sleep(0.01)
                    except Exception as e:
                        print(f"SSH veri okuma hatası: {str(e)}")
                        socketio.emit('connection_error', {'error': f'SSH okuma hatası: {str(e)}'},
                                     namespace='/terminal', room=client_sid)
                
                # İstemci kimliğini thread'e geçir
                thread = threading.Thread(
                    target=read_from_ssh,
                    args=(request.sid, channel),
                    daemon=True
                )
                thread.start()
                
                # SSH bilgilerini oturuma kaydet
                session_info = {
                    'session_id': session_id,
                    'type': session_type,
                    'host': host,
                    'port': port,
                    'username': username,
                    'ssh_client': ssh_client,
                    'channel': channel,
                    'thread': thread,
                    'recording': False,
                    'start_time': datetime.datetime.now(),
                    'recording_data': []
                }
                terminal_sessions[request.sid] = session_info
                
                # Oturum oluşturuldu bilgisi gönder
                emit('session_created', {'session_id': session_id})
                
                print(f"SSH terminal oturumu oluşturuldu: {session_id}")
                return
                
            except Exception as e:
                emit('connection_error', {'error': f'SSH bağlantı hatası: {str(e)}'})
                print(f"SSH bağlantı hatası: {str(e)}")
                traceback.print_exc()
                return
        
        # Oturum bilgilerini kaydet
        session_info = {
            'session_id': session_id,
            'type': session_type,
            'target': target,
            'host': host,
            'fd': fd,
            'pid': pid,
            'recording': False,
            'start_time': datetime.datetime.now(),
            'recording_data': []
        }
        
        # Oturum oluşturuldu bilgisi gönder
        emit('session_created', {'session_id': session_id})
        
        print(f"Terminal oturumu oluşturuldu: {session_id}")
        
        # Terminal kayıt dizini oluştur
        os.makedirs('terminal_recordings', exist_ok=True)
        
    except Exception as e:
        emit('connection_error', {'error': f'Oturum oluşturma hatası: {str(e)}'})
        print(f"Oturum oluşturma hatası: {str(e)}")
        traceback.print_exc()

@socketio.on('terminal_input', namespace='/terminal')
def handle_terminal_input(data):
    try:
        print(f"Terminal input alındı: {data}")
        session_id = data.get('session_id')
        input_data = data.get('data')
        
        # Oturumu bul
        session_info = None
        for sid, session in terminal_sessions.items():
            if session.get('session_id') == session_id:
                session_info = session
                break
        
        if not session_info:
            emit('connection_error', {'error': 'Oturum bulunamadı'})
            return
        
        # Oturum tipine göre input gönder
        if session_info['type'] == 'container':
            if 'exec_id' in session_info:
                try:
                    session_info['exec_id'].send(input_data.encode('utf-8'))
                except Exception as e:
                    emit('connection_error', {'error': f'Konteyner input hatası: {str(e)}'})
        
        elif session_info['type'] == 'host':
            if session_info.get('fd'):
                try:
                    os.write(session_info['fd'], input_data.encode('utf-8'))
                except Exception as e:
                    emit('connection_error', {'error': f'Host input hatası: {str(e)}'})
        
        elif session_info['type'] == 'ssh':
            if 'channel' in session_info:
                try:
                    session_info['channel'].send(input_data)
                except Exception as e:
                    emit('connection_error', {'error': f'SSH input hatası: {str(e)}'})
        
        # Kayıt yapılıyorsa verileri ekle
        if session_info.get('recording', False):
            session_info['recording_data'].append({
                'timestamp': time.time() - session_info.get('recording_start_time', 0),
                'data': input_data,
                'type': 'input'
            })
    
    except Exception as e:
        emit('connection_error', {'error': f'Terminal input hatası: {str(e)}'})
        print(f"Terminal input hatası: {str(e)}")
        traceback.print_exc()

@socketio.on('terminal_resize', namespace='/terminal')
def handle_terminal_resize(data):
    try:
        session_id = data.get('session_id')
        cols = data.get('cols', 80)
        rows = data.get('rows', 24)
        
        # Oturumu bul
        session_info = None
        for sid, session in terminal_sessions.items():
            if session.get('session_id') == session_id:
                session_info = session
                break
        
        if not session_info:
            return
        
        # Oturum tipine göre boyut ayarla
        if session_info['type'] == 'host' and session_info.get('fd'):
            try:
                fcntl.ioctl(session_info['fd'], termios.TIOCSWINSZ, 
                            struct.pack("HHHH", rows, cols, 0, 0))
            except Exception as e:
                print(f"Terminal boyut değiştirme hatası: {str(e)}")
    
    except Exception as e:
        print(f"Terminal boyut değiştirme hatası: {str(e)}")
        traceback.print_exc()

@socketio.on('close_session', namespace='/terminal')
def close_terminal_session(data):
    try:
        session_id = data.get('session_id')
        
        # Oturumu bul
        session_info = None
        sid_to_remove = None
        for sid, session in terminal_sessions.items():
            if session.get('session_id') == session_id:
                session_info = session
                sid_to_remove = sid
                break
        
        if not session_info:
            return
        
        # Oturum tipine göre kapat
        if session_info['type'] == 'container':
            if 'exec_id' in session_info:
                try:
                    session_info['exec_id'].close()
                except:
                    pass
        
        elif session_info['type'] == 'host':
            if session_info.get('pid'):
                try:
                    os.kill(session_info['pid'], signal.SIGTERM)
                except:
                    pass
                
            if session_info.get('fd'):
                try:
                    os.close(session_info['fd'])
                except:
                    pass
        
        elif session_info['type'] == 'ssh':
            if 'channel' in session_info:
                try:
                    session_info['channel'].close()
                except:
                    pass
                
            if 'ssh_client' in session_info:
                try:
                    session_info['ssh_client'].close()
                except:
                    pass
        
        # Kayıt yapılıyorsa durdur
        if session_info.get('recording', False):
            session_info['recording'] = False
            session_info['end_time'] = datetime.datetime.now()
            
            # Kayıt dosyasını oluştur
            recording_file = os.path.join('terminal_recordings', f"{session_id}.json")
            with open(recording_file, 'w') as f:
                json.dump({
                    'session_id': session_id,
                    'type': session_info.get('type'),
                    'target': session_info.get('target'),
                    'host': session_info.get('host'),
                    'start_time': session_info.get('start_time').isoformat(),
                    'end_time': session_info.get('end_time').isoformat(),
                    'frames': session_info.get('recording_data', [])
                }, f)
        
        # Thread sonlandır
        if 'thread' in session_info and session_info['thread'].is_alive():
            # Thread sonlandırma işlemi burada yapılabilir
            # Python thread'leri doğrudan kill edilemez, ancak
            # thread fonksiyonları içinde exit flag kontrol edilebilir
            pass
        
        # Oturumu sil
        if sid_to_remove:
            terminal_sessions.pop(sid_to_remove, None)
    
    except Exception as e:
        print(f"Oturum kapatma hatası: {str(e)}")
        traceback.print_exc()

@socketio.on('start_recording', namespace='/terminal')
def start_terminal_recording(data):
    try:
        session_id = data.get('session_id')
        
        # Oturumu bul
        session_info = None
        for sid, session in terminal_sessions.items():
            if session.get('session_id') == session_id:
                session_info = session
                break
        
        if not session_info:
            emit('connection_error', {'error': 'Oturum bulunamadı'})
            return
        
        # Kayıt başlat
        session_info['recording'] = True
        session_info['recording_start_time'] = time.time()
        session_info['recording_data'] = []
        
        emit('recording_started', {'session_id': session_id})
    
    except Exception as e:
        emit('connection_error', {'error': f'Kayıt başlatma hatası: {str(e)}'})
        print(f"Kayıt başlatma hatası: {str(e)}")
        traceback.print_exc()

# Eski "start" olayını yeni "create_session" olayına yönlendir
@socketio.on('start', namespace='/terminal')
def legacy_start_terminal(data):
    """Eski istemci uyumluluğu için start olayını create_session'a yönlendir"""
    print(f"Eski 'start' olayı alındı, yeni API'ye yönlendiriliyor: {data}")
    
    # Veri formatını yeni API'ye uyarla
    connection_type = data.get('type')
    
    new_data = {
        'type': connection_type
    }
    
    if connection_type == 'container':
        new_data['target'] = data.get('containerId')
    elif connection_type == 'ssh':
        new_data['host'] = data.get('host')
        new_data['port'] = data.get('port', '22')
        new_data['username'] = data.get('username')
        new_data['password'] = data.get('password')
    
    # Yeni oturum oluşturma fonksiyonunu çağır
    create_terminal_session(new_data)

# Eski "data" olayını yeni "terminal_input" olayına yönlendir
@socketio.on('data', namespace='/terminal')
def legacy_terminal_input(data):
    """Eski istemci uyumluluğu için data olayını terminal_input'a yönlendir"""
    print(f"Eski 'data' olayı alındı, yeni API'ye yönlendiriliyor")
    
    # Oturumu bul
    session_info = terminal_sessions.get(request.sid)
    if not session_info:
        print("İstemci için aktif oturum bulunamadı")
        return
    
    # Yeni formatta veriyi gönder
    handle_terminal_input({
        'session_id': session_info.get('session_id'),
        'data': data
    })

# Eski "resize" olayını yeni "terminal_resize" olayına yönlendir
@socketio.on('resize', namespace='/terminal')
def legacy_terminal_resize(data):
    """Eski istemci uyumluluğu için resize olayını terminal_resize'a yönlendir"""
    print(f"Eski 'resize' olayı alındı, yeni API'ye yönlendiriliyor")
    
    # Oturumu bul
    session_info = terminal_sessions.get(request.sid)
    if not session_info:
        print("İstemci için aktif oturum bulunamadı")
        return
    
    # Yeni formatta veriyi gönder
    handle_terminal_resize({
        'session_id': session_info.get('session_id'),
        'cols': data.get('cols', 80),
        'rows': data.get('rows', 24)
    })

# Terminal sayfası
@app.route('/terminal')
def terminal():
    """Terminal sayfasını görüntüle"""
    return render_template('terminal.html', title='Terminal')

# Çalışan containerları getir (terminal için)
@app.route('/api/containers')
def get_containers_api():
    """Çalışan container listesini getir"""
    try:
        if docker_client:
            containers = docker_client.containers.list(filters={"status": "running"})
            container_list = []
            
            for container in containers:
                container_list.append({
                    'id': container.id,
                    'name': container.name
                })
            
            return jsonify(container_list)
        else:
            # Docker bağlantısı yoksa mock veri göster
            print("Docker bağlantısı kurulamadı. Mock veri gösteriliyor.")
            mock_containers = get_mock_containers()
            container_list = []
            
            for container in mock_containers:
                if container['status'] == 'running':
                    container_list.append({
                        'id': container['id'],
                        'name': container['name']
                    })
            
            return jsonify(container_list)
    except Exception as e:
        print(f"Konteyner listesi alınırken hata: {str(e)}")
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
        if docker_client:
            # Docker API ile istatistikleri al
            containers = docker_client.containers.list(all=True)
            running_containers = [c for c in containers if c.status == 'running']
            images = docker_client.images.list()
            volumes = docker_client.volumes.list()
            networks = docker_client.networks.list()
            
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
        if docker_client:
            containers = docker_client.containers.list(all=True)
        else:
            # Docker bağlantısı yoksa mock veri göster
            print("Docker bağlantısı kurulamadı. Mock veri gösteriliyor.")
            containers = get_mock_containers()
            return render_template('containers.html', containers=containers, title='Konteynerler')
    except Exception as e:
        flash(f"Konteyner listesi alınırken hata: {str(e)}", "error")
        containers = []
    
    return render_template('containers.html', containers=containers, title='Konteynerler')

@app.route('/containers/<id>')
def container_detail(id):
    try:
        if docker_client:
            container = docker_client.containers.get(id)
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
        if docker_client:
            container = docker_client.containers.get(id)
            container.start()
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
        if docker_client:
            container = docker_client.containers.get(id)
            container.stop()
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
        if docker_client:
            container = docker_client.containers.get(id)
            container.restart()
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
        if docker_client:
            container = docker_client.containers.get(id)
            container.remove(force=True)
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
        if docker_client:
            container = docker_client.containers.get(id)
            logs = container.logs(tail=100).decode('utf-8')
        else:
            flash("Docker bağlantısı kurulamadı.", "error")
            return redirect(url_for('container_list'))
            
        return render_template('container_logs.html', container=container, logs=logs)
    except Exception as e:
        flash(f"Container logları alınamadı: {e}", "error")
        return redirect(url_for('container_detail', id=id))

@app.route('/images')
def image_list_page():
    try:
        if docker_client:
            images = docker_client.images.list()
        else:
            # Docker bağlantısı yoksa mock veri göster
            print("Docker bağlantısı kurulamadı. Mock veri gösteriliyor.")
            images = get_mock_images()
            return render_template('images.html', images=images, title='İmajlar')
    except Exception as e:
        flash(f"İmaj listesi alınırken hata: {str(e)}", "error")
        images = []
    
    return render_template('images.html', images=images, title='İmajlar')

@app.route('/networks')
def network_list_page():
    try:
        if docker_client:
            networks = docker_client.networks.list()
        else:
            # Docker bağlantısı yoksa mock veri göster
            print("Docker bağlantısı kurulamadı. Mock veri gösteriliyor.")
            networks = get_mock_networks()
            return render_template('networks.html', networks=networks, title='Ağlar')
    except Exception as e:
        flash(f"Ağ listesi alınırken hata: {str(e)}", "error")
        networks = []
    
    return render_template('networks.html', networks=networks, title='Ağlar')

@app.route('/volumes')
def volume_list_page():
    try:
        if docker_client:
            volumes = docker_client.volumes.list()
        else:
            # Docker bağlantısı yoksa mock veri göster
            print("Docker bağlantısı kurulamadı. Mock veri gösteriliyor.")
            volumes = get_mock_volumes()
            return render_template('volumes.html', volumes=volumes, title='Volumeler')
    except Exception as e:
        flash(f"Volume listesi alınırken hata: {str(e)}", "error")
        volumes = []
    
    return render_template('volumes.html', volumes=volumes, title='Volumeler')

@app.route('/api/stats')
def get_stats():
    """Docker istatistiklerini getir"""
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
        if docker_client:
            # Docker API ile istatistikleri al
            containers = docker_client.containers.list(all=True)
            running_containers = [c for c in containers if c.status == 'running']
            images = docker_client.images.list()
            volumes = docker_client.volumes.list()
            networks = docker_client.networks.list()
            
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
        else:
            # Docker bağlantısı yoksa mock veri göster
            print("Docker bağlantısı kurulamadı. Mock veri gösteriliyor.")
            mock_containers = get_mock_containers()
            running_containers = [c for c in mock_containers if c['status'] == 'running']
            mock_images = get_mock_images()
            mock_volumes = get_mock_volumes()
            mock_networks = get_mock_networks()
            
            stats.update({
                'containers': {
                    'total': len(mock_containers),
                    'running': len(running_containers),
                    'stopped': len(mock_containers) - len(running_containers)
                },
                'images': len(mock_images),
                'volumes': len(mock_volumes),
                'networks': len(mock_networks)
            })
    except Exception as e:
        print(f"İstatistikler alınırken hata: {str(e)}")
    
    return jsonify(stats)

@app.route('/api/status')
def api_status():
    """Docker bağlantı durumunu kontrol et"""
    try:
        if docker_client:
            version = docker_client.version()
            return jsonify({
                'status': 'connected',
                'client': 'api',
                'version': version.get('Version', 'bilinmiyor'),
                'api_version': version.get('ApiVersion', 'bilinmiyor')
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

# Mock veri fonksiyonları - Docker bağlantısı olmadığında kullanılır
def get_mock_containers():
    """Mock konteyner verileri"""
    return [
        {
            'id': 'abc123456789',
            'name': 'mock_nginx',
            'image': 'nginx:latest',
            'status': 'running',
            'created': '2023-05-15T10:00:00Z',
            'ports': '80/tcp, 443/tcp',
            'command': 'nginx -g daemon off;'
        },
        {
            'id': 'def789012345',
            'name': 'mock_redis',
            'image': 'redis:alpine',
            'status': 'running',
            'created': '2023-05-15T11:00:00Z',
            'ports': '6379/tcp',
            'command': 'redis-server'
        },
        {
            'id': 'ghi456789012',
            'name': 'mock_postgres',
            'image': 'postgres:14',
            'status': 'exited',
            'created': '2023-05-14T09:00:00Z',
            'ports': '5432/tcp',
            'command': 'postgres'
        }
    ]

def get_mock_images():
    """Mock imaj verileri"""
    return [
        {
            'id': 'sha256:a1b2c3d4e5f6',
            'tags': ['nginx:latest'],
            'created': '2023-04-10T08:00:00Z',
            'size': '140MB'
        },
        {
            'id': 'sha256:g7h8i9j0k1l2',
            'tags': ['redis:alpine'],
            'created': '2023-04-05T08:00:00Z',
            'size': '32MB'
        },
        {
            'id': 'sha256:m3n4o5p6q7r8',
            'tags': ['postgres:14'],
            'created': '2023-03-20T08:00:00Z',
            'size': '374MB'
        }
    ]

def get_mock_networks():
    """Mock ağ verileri"""
    return [
        {
            'id': 'net123456789',
            'name': 'bridge',
            'driver': 'bridge',
            'scope': 'local',
            'created': '2023-01-01T00:00:00Z'
        },
        {
            'id': 'net234567890',
            'name': 'host',
            'driver': 'host',
            'scope': 'local',
            'created': '2023-01-01T00:00:00Z'
        },
        {
            'id': 'net345678901',
            'name': 'mock_network',
            'driver': 'bridge',
            'scope': 'local',
            'created': '2023-05-01T10:00:00Z'
        }
    ]

def get_mock_volumes():
    """Mock volume verileri"""
    return [
        {
            'name': 'mock_data',
            'driver': 'local',
            'mountpoint': '/var/lib/docker/volumes/mock_data/_data',
            'created': '2023-05-01T10:00:00Z'
        },
        {
            'name': 'mock_postgres_data',
            'driver': 'local',
            'mountpoint': '/var/lib/docker/volumes/mock_postgres_data/_data',
            'created': '2023-04-15T09:00:00Z'
        }
    ]

# Ana döngü
if __name__ == '__main__':
    try:
        print("Chronis uygulaması başlatılıyor...")
        import eventlet.wsgi
        from eventlet import wsgi
        
        # Docker'a bağlan
        connect_to_docker()
        
        # allow_unsafe_werkzeug parametresini kullanmadan başlat
        # eventlet.wsgi.server yerine doğrudan socketio.run kullan
        socketio.run(app, host='0.0.0.0', port=5000, debug=True)
    except Exception as e:
        print(f"Hata: {e}")
        traceback.print_exc() 