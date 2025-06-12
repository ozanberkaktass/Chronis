from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
import docker
import os
import json
from datetime import datetime

# Flask uygulamasını başlat ve şablon klasörünü doğru şekilde ayarla
template_dir = os.path.abspath('app/templates')
static_dir = os.path.abspath('app/static')
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.secret_key = "chronis_gizli_anahtar"  # Gerçek uygulamada değiştirin

# Global değişken olarak Docker istemcisini tanımla
client = None

# Docker istemcisini başlat
try:
    # Docker socket yolu
    socket_path = '/var/run/docker.sock'
    
    # Docker istemcisini oluştur
    # Eğer DOCKER_HOST çevre değişkeni tanımlıysa, onu kullan
    if os.environ.get('DOCKER_HOST'):
        client = docker.from_env()
        print(f"DOCKER_HOST çevre değişkeniyle bağlanma deneniyor: {os.environ.get('DOCKER_HOST')}")
    else:
        # Doğrudan socket yolunu belirt
        client = docker.DockerClient(base_url=f"unix://{socket_path}")
        print(f"Unix socket ile bağlanma deneniyor: {socket_path}")
    
    # Bağlantıyı test et
    version = client.version()
    print(f"Docker bağlantısı başarılı. Docker versiyonu: {version.get('Version', 'bilinmiyor')}")
    
except Exception as e:
    print(f"Docker bağlantısı kurulamadı: {e}")
    client = None

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
            # Docker istatistikleri
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
        else:
            flash("Docker bağlantısı kurulamadı. Mock veri gösteriliyor.", "error")
        
        return render_template('dashboard.html', stats=stats)
    except Exception as e:
        flash(f"Docker bilgileri alınamadı: {e}", "error")
        return render_template('dashboard.html', stats=stats, error=str(e))

@app.route('/containers')
def container_list():
    try:
        containers = client.containers.list(all=True)
        return render_template('containers.html', containers=containers)
    except Exception as e:
        flash(f"Container listesi alınamadı: {e}", "error")
        return render_template('containers.html', error=str(e))

@app.route('/containers/<id>')
def container_detail(id):
    try:
        container = client.containers.get(id)
        return render_template('container_detail.html', container=container)
    except Exception as e:
        flash(f"Container detayları alınamadı: {e}", "error")
        return redirect(url_for('container_list'))

@app.route('/containers/start/<id>', methods=['POST'])
def start_container(id):
    try:
        container = client.containers.get(id)
        container.start()
        flash(f"Container {container.name} başlatıldı", "success")
    except Exception as e:
        flash(f"Container başlatılamadı: {e}", "error")
    return redirect(url_for('container_list'))

@app.route('/containers/stop/<id>', methods=['POST'])
def stop_container(id):
    try:
        container = client.containers.get(id)
        container.stop()
        flash(f"Container {container.name} durduruldu", "success")
    except Exception as e:
        flash(f"Container durdurulamadı: {e}", "error")
    return redirect(url_for('container_list'))

@app.route('/containers/restart/<id>', methods=['POST'])
def restart_container(id):
    try:
        container = client.containers.get(id)
        container.restart()
        flash(f"Container {container.name} yeniden başlatıldı", "success")
    except Exception as e:
        flash(f"Container yeniden başlatılamadı: {e}", "error")
    return redirect(url_for('container_list'))

@app.route('/containers/remove/<id>', methods=['POST'])
def remove_container(id):
    try:
        container = client.containers.get(id)
        container.remove(force=True)
        flash(f"Container {container.name} silindi", "success")
    except Exception as e:
        flash(f"Container silinemedi: {e}", "error")
    return redirect(url_for('container_list'))

@app.route('/containers/logs/<id>')
def container_logs(id):
    try:
        container = client.containers.get(id)
        logs = container.logs(tail=100).decode('utf-8')
        return render_template('container_logs.html', container=container, logs=logs)
    except Exception as e:
        flash(f"Container logları alınamadı: {e}", "error")
        return redirect(url_for('container_detail', id=id))

@app.route('/images')
def image_list():
    try:
        images = client.images.list()
        return render_template('images.html', images=images)
    except Exception as e:
        flash(f"Image listesi alınamadı: {e}", "error")
        return render_template('images.html', error=str(e))

@app.route('/networks')
def network_list():
    try:
        networks = client.networks.list()
        return render_template('networks.html', networks=networks)
    except Exception as e:
        flash(f"Network listesi alınamadı: {e}", "error")
        return render_template('networks.html', error=str(e))

@app.route('/volumes')
def volume_list():
    try:
        volumes = client.volumes.list()
        return render_template('volumes.html', volumes=volumes)
    except Exception as e:
        flash(f"Volume listesi alınamadı: {e}", "error")
        return render_template('volumes.html', error=str(e))

@app.route('/api/stats')
def api_stats():
    try:
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
        
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000) 