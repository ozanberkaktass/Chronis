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
import logging
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, session
from flask_socketio import SocketIO, emit, disconnect
from werkzeug.utils import secure_filename
from docker_utils import get_docker_client, list_containers, get_container_status, retry_docker_operation, DockerCLIClient

# WebSocket için eventlet'i kullan
eventlet.monkey_patch()

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

# Loglama ayarları
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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

# Docker bağlantısını birkaç kez deneme
def connect_to_docker(max_attempts=3, delay=1):
    """Docker bağlantısını farklı yöntemler ile deneyerek kurar"""
    global docker_client
    
    logger.info("Docker bağlantısı kuruluyor...")
    try:
        # docker_utils modülünden Docker istemcisini al
        docker_client = get_docker_client()
        logger.info("Docker bağlantısı başarılı")
        return True
    except Exception as e:
        logger.error(f"Docker bağlantısı başarısız: {str(e)}")
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
                    timeout=30,
                    allow_agent=False,
                    look_for_keys=False
                )
                
                # PTY oluştur
                transport = ssh_client.get_transport()
                transport.set_keepalive(60)  # 60 saniyede bir keepalive paketi gönder
                
                channel = transport.open_session()
                channel.get_pty(term='xterm-256color', width=80, height=24)
                channel.invoke_shell()
                
                # Terminal girişi göndermeden önce 1 saniye bekle, bazı SSH sunucuları için faydalı olabilir
                time.sleep(1)
                # Başlangıç komutu olarak Enter tuşuna basma (bazı SSH sunucuları için gerekli)
                channel.send("\r\n")
                
                # Terminali okuma işlevi
                def read_from_ssh(client_sid, ssh_channel):
                    try:
                        # İlk hoş geldin mesajını okumak için zaman ver
                        time.sleep(0.5)
                        
                        # Başlangıç verilerini okumak için kontrol et
                        if ssh_channel.recv_ready():
                            initial_data = ssh_channel.recv(4096).decode('utf-8', errors='ignore')
                            if initial_data:
                                print(f"SSH ilk veri alındı ({len(initial_data)} bayt)")
                                socketio.emit('terminal_output', {'output': initial_data}, namespace='/terminal', room=client_sid)
                        
                        # Ana okuma döngüsü
                        while True:
                            # Bağlantı kesildi mi kontrol et
                            if ssh_channel.closed or not ssh_channel.get_transport() or not ssh_channel.get_transport().is_active():
                                print(f"SSH bağlantısı kapandı: {client_sid}")
                                socketio.emit('connection_error', {'error': 'SSH bağlantısı kapandı'}, 
                                             namespace='/terminal', room=client_sid)
                                break
                            
                            # Veri var mı kontrol et
                            if ssh_channel.recv_ready():
                                data = ssh_channel.recv(4096).decode('utf-8', errors='ignore')
                                if data:
                                    # Debug için veri içeriğini yazdır
                                    print(f"SSH veri alındı ({len(data)} bayt): {repr(data)[:50]}...")
                                    socketio.emit('terminal_output', {'output': data}, namespace='/terminal', room=client_sid)
                            
                            # Hata varsa kontrol et
                            if ssh_channel.recv_stderr_ready():
                                err_data = ssh_channel.recv_stderr(4096).decode('utf-8', errors='ignore')
                                if err_data:
                                    print(f"SSH stderr alındı: {repr(err_data)}")
                                    socketio.emit('terminal_output', {'output': err_data}, namespace='/terminal', room=client_sid)
                            
                            # Küçük bir bekleme ile CPU kullanımını azalt
                            time.sleep(0.05)
                    except Exception as e:
                        print(f"SSH veri okuma hatası: {str(e)}")
                        traceback.print_exc()
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
        print(f"Terminal input alındı: {repr(data)[:50]}...")
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
                    print(f"Konteyner veri gönderildi: {repr(input_data)[:30]}...")
                except Exception as e:
                    print(f"Konteyner input hatası: {str(e)}")
                    traceback.print_exc()
                    emit('connection_error', {'error': f'Konteyner input hatası: {str(e)}'})
        
        elif session_info['type'] == 'host':
            if session_info.get('fd'):
                try:
                    os.write(session_info['fd'], input_data.encode('utf-8'))
                    print(f"Host veri gönderildi: {repr(input_data)[:30]}...")
                except Exception as e:
                    print(f"Host input hatası: {str(e)}")
                    traceback.print_exc()
                    emit('connection_error', {'error': f'Host input hatası: {str(e)}'})
        
        elif session_info['type'] == 'ssh':
            if 'channel' in session_info:
                try:
                    if not isinstance(input_data, bytes):
                        send_data = input_data.encode('utf-8') if isinstance(input_data, str) else input_data
                    else:
                        send_data = input_data
                    
                    session_info['channel'].send(send_data)
                    print(f"SSH veri gönderildi ({len(send_data)} bayt): {repr(input_data)[:30]}...")
                except Exception as e:
                    print(f"SSH input hatası: {str(e)}")
                    traceback.print_exc()
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

# Terminal2 sayfası
@app.route('/terminal2')
def terminal2():
    return render_template('terminal2.html')

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