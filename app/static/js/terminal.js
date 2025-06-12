/**
 * Chronis - Terminal İşlevselliği
 * WebSocket tabanlı terminal iletişimi ve kayıt/oynatma işlemleri
 */

document.addEventListener('DOMContentLoaded', function() {
    // Değişkenler
    let terminal;
    let socket;
    let currentSession = null;
    let isRecording = false;
    let playbackTerminal;
    let playbackData = [];
    let playbackInterval;
    let playbackIndex = 0;
    
    // DOM Elementleri
    const terminalContainer = document.getElementById('terminal');
    const terminalPlaceholder = document.getElementById('terminal-placeholder');
    const activeConnection = document.getElementById('activeConnection');
    const activeTarget = document.getElementById('activeTarget');
    const connectionType = document.getElementById('connectionType');
    const containerSection = document.getElementById('containerSection');
    const hostSection = document.getElementById('hostSection');
    const sshSection = document.getElementById('sshSection');
    const containerSelect = document.getElementById('containerSelect');
    const sshAuthType = document.getElementById('sshAuthType');
    const passwordSection = document.getElementById('passwordSection');
    const keySection = document.getElementById('keySection');
    const recordToggle = document.getElementById('recordToggle');
    const disconnectBtn = document.getElementById('disconnectBtn');
    const sessionsList = document.getElementById('sessionsList');
    
    // Terminal başlatma
    function initTerminal() {
        // Eğer terminal zaten oluşturulmuşsa temizle
        if (terminal) {
            terminal.dispose();
        }
        
        // Yeni terminal oluştur
        terminal = new Terminal({
            cursorBlink: true,
            scrollback: 1000,
            theme: {
                background: '#1e1e1e',
                foreground: '#f0f0f0',
                cursor: '#f0f0f0'
            }
        });
        
        // xterm.js'e fit eklentisini yükle
        Terminal.applyAddon(fit);
        
        // Terminali container'a bağla
        terminal.open(terminalContainer);
        terminal.fit();
        
        // Terminal boyutu değişikliği
        window.addEventListener('resize', () => {
            if (terminal) {
                terminal.fit();
                if (socket && socket.connected) {
                    socket.emit('resize', {
                        cols: terminal.cols,
                        rows: terminal.rows
                    });
                }
            }
        });
        
        return terminal;
    }
    
    // İzleme terminali başlatma
    function initPlaybackTerminal() {
        if (playbackTerminal) {
            playbackTerminal.dispose();
        }
        
        // Yeni terminal oluştur
        playbackTerminal = new Terminal({
            cursorBlink: true,
            scrollback: 1000,
            theme: {
                background: '#1e1e1e',
                foreground: '#f0f0f0',
                cursor: '#f0f0f0'
            }
        });
        
        // xterm.js'e fit eklentisini yükle
        Terminal.applyAddon(fit);
        
        // Terminali container'a bağla
        const playbackTerminalContainer = document.getElementById('playback-terminal');
        playbackTerminal.open(playbackTerminalContainer);
        playbackTerminal.fit();
        
        return playbackTerminal;
    }
    
    // Bağlantı tipine göre alanları göster/gizle
    connectionType.addEventListener('change', function() {
        const type = this.value;
        
        containerSection.style.display = type === 'container' ? 'block' : 'none';
        hostSection.style.display = type === 'host' ? 'block' : 'none';
        sshSection.style.display = type === 'ssh' ? 'block' : 'none';
        
        // Container listesini yükle
        if (type === 'container') {
            loadContainers();
        }
    });
    
    // SSH kimlik doğrulama tipine göre alanları göster/gizle
    sshAuthType.addEventListener('change', function() {
        const type = this.value;
        
        passwordSection.style.display = type === 'password' ? 'block' : 'none';
        keySection.style.display = type === 'key' ? 'block' : 'none';
    });
    
    // Container listesini yükle
    function loadContainers() {
        fetch('/api/containers/running')
            .then(response => response.json())
            .then(data => {
                containerSelect.innerHTML = '';
                
                if (data.length === 0) {
                    const option = document.createElement('option');
                    option.value = '';
                    option.textContent = 'Çalışan container bulunamadı';
                    containerSelect.appendChild(option);
                } else {
                    data.forEach(container => {
                        const option = document.createElement('option');
                        option.value = container.id;
                        option.textContent = container.name;
                        containerSelect.appendChild(option);
                    });
                }
            })
            .catch(error => {
                console.error('Container listesi alınamadı:', error);
                containerSelect.innerHTML = '<option value="">Hata: Container listesi alınamadı</option>';
            });
    }
    
    // Terminal oturumu başlat
    document.getElementById('startSessionBtn').addEventListener('click', function() {
        const type = connectionType.value;
        let target = '';
        let params = {};
        
        // Bağlantı tipine göre parametreleri hazırla
        if (type === 'container') {
            if (!containerSelect.value) {
                alert('Lütfen bir container seçin.');
                return;
            }
            target = containerSelect.options[containerSelect.selectedIndex].textContent;
            params = {
                type: 'container',
                containerId: containerSelect.value,
                cmd: document.getElementById('containerCmd').value || '/bin/bash'
            };
        } else if (type === 'host') {
            target = 'Host';
            params = {
                type: 'host'
            };
        } else if (type === 'ssh') {
            const host = document.getElementById('sshHost').value;
            const username = document.getElementById('sshUsername').value;
            
            if (!host || !username) {
                alert('Lütfen SSH host ve kullanıcı adı girin.');
                return;
            }
            
            target = `${username}@${host}`;
            params = {
                type: 'ssh',
                host: host,
                port: document.getElementById('sshPort').value,
                username: username,
                authType: sshAuthType.value
            };
            
            if (sshAuthType.value === 'password') {
                const password = document.getElementById('sshPassword').value;
                if (!password) {
                    alert('Lütfen şifre girin.');
                    return;
                }
                params.password = password;
            } else {
                const key = document.getElementById('sshKey').value;
                if (!key) {
                    alert('Lütfen SSH anahtarı girin.');
                    return;
                }
                params.key = key;
            }
        }
        
        // Kayıt seçeneğini al
        const recordSession = document.getElementById('recordSession').checked;
        
        // Modali kapat
        const modal = bootstrap.Modal.getInstance(document.getElementById('newSessionModal'));
        modal.hide();
        
        // Terminal görünümünü ayarla
        terminalPlaceholder.style.display = 'none';
        terminalContainer.style.display = 'block';
        
        // Terminali başlat ve bağlantıyı kur
        const term = initTerminal();
        term.writeln('Bağlanıyor...');
        
        // Socket.io bağlantısı
        socket = io.connect('/terminal', {
            transports: ['websocket', 'polling'], 
            upgrade: true,
            rememberUpgrade: true,
            forceNew: true,
            reconnection: true,
            reconnectionAttempts: 5,
            reconnectionDelay: 1000
        });
        
        // Bağlantı kurulduğunda
        socket.on('connect', () => {
            // Terminal oturumu başlat
            socket.emit('start', {
                ...params,
                cols: term.cols,
                rows: term.rows,
                record: recordSession
            });
            
            // Aktif bağlantı bilgilerini güncelle
            activeConnection.style.display = 'inline-block';
            activeTarget.textContent = target;
            recordToggle.disabled = false;
            disconnectBtn.disabled = false;
            
            // Kayıt durumunu ayarla
            isRecording = recordSession;
            updateRecordButton();
            
            // Oturum bilgilerini kaydet
            currentSession = {
                id: socket.id,
                target: target,
                type: type,
                startTime: new Date(),
                recording: recordSession
            };
        });
        
        // Terminal veri alındığında
        socket.on('data', (data) => {
            term.write(data);
        });
        
        // Terminal veri gönderildiğinde
        term.onData(data => {
            socket.emit('data', data);
        });
        
        // Bağlantı kesildiğinde
        socket.on('disconnect', () => {
            term.writeln('\r\n\nBağlantı kesildi.');
            resetConnection();
        });
        
        // Hata durumunda
        socket.on('error', (error) => {
            term.writeln(`\r\n\nHata: ${error}`);
            resetConnection();
        });
    });
    
    // Kayıt düğmesini güncelle
    function updateRecordButton() {
        if (isRecording) {
            recordToggle.innerHTML = '<i class="fas fa-stop text-danger"></i> <span data-i18n="stop_recording">Kaydı Durdur</span>';
            recordToggle.classList.remove('btn-outline-primary');
            recordToggle.classList.add('btn-outline-danger');
        } else {
            recordToggle.innerHTML = '<i class="fas fa-circle text-danger"></i> <span data-i18n="record">Kaydet</span>';
            recordToggle.classList.remove('btn-outline-danger');
            recordToggle.classList.add('btn-outline-primary');
        }
    }
    
    // Kayıt düğmesi tıklandığında
    recordToggle.addEventListener('click', function() {
        if (!socket || !socket.connected) return;
        
        isRecording = !isRecording;
        socket.emit('toggleRecord', { recording: isRecording });
        updateRecordButton();
        
        if (isRecording) {
            showToast('Oturum kaydı başlatıldı');
        } else {
            showToast('Oturum kaydı durduruldu');
        }
    });
    
    // Bağlantıyı kes düğmesi tıklandığında
    disconnectBtn.addEventListener('click', function() {
        if (!socket || !socket.connected) return;
        
        socket.disconnect();
        resetConnection();
    });
    
    // Bağlantıyı sıfırla
    function resetConnection() {
        activeConnection.style.display = 'none';
        activeTarget.textContent = '-';
        recordToggle.disabled = true;
        disconnectBtn.disabled = true;
        
        // Terminal görünümünü sıfırla
        terminalContainer.style.display = 'none';
        terminalPlaceholder.style.display = 'flex';
        
        // Oturum bilgilerini sıfırla
        if (currentSession) {
            currentSession.endTime = new Date();
            currentSession = null;
        }
        
        // Socket bağlantısını kapat
        if (socket) {
            socket.disconnect();
            socket = null;
        }
    }
    
    // Oturumlar modalı açıldığında oturumları yükle
    document.getElementById('sessionsBtn').addEventListener('click', function() {
        loadSessions();
    });
    
    // Oturumları yükle
    function loadSessions() {
        fetch('/api/terminal/sessions')
            .then(response => response.json())
            .then(data => {
                sessionsList.innerHTML = '';
                
                if (data.length === 0) {
                    sessionsList.innerHTML = '<tr><td colspan="6" class="text-center" data-i18n="no_sessions">Kayıtlı oturum bulunamadı.</td></tr>';
                } else {
                    data.forEach(session => {
                        const startTime = new Date(session.start_time);
                        const endTime = new Date(session.end_time);
                        const duration = Math.round((endTime - startTime) / 1000);
                        
                        const minutes = Math.floor(duration / 60);
                        const seconds = duration % 60;
                        const durationText = `${minutes}m ${seconds}s`;
                        
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td>${session.target}</td>
                            <td>${session.type}</td>
                            <td>${session.user}</td>
                            <td>${startTime.toLocaleString()}</td>
                            <td>${durationText}</td>
                            <td>
                                <button class="btn btn-sm btn-primary playback-btn" data-id="${session.id}">
                                    <i class="fas fa-play"></i>
                                </button>
                                <button class="btn btn-sm btn-danger delete-btn" data-id="${session.id}">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </td>
                        `;
                        sessionsList.appendChild(row);
                    });
                    
                    // İzleme düğmelerine olay dinleyicileri ekle
                    document.querySelectorAll('.playback-btn').forEach(button => {
                        button.addEventListener('click', function() {
                            const recordingId = this.getAttribute('data-id');
                            openPlaybackModal(recordingId);
                        });
                    });
                    
                    // Silme düğmelerine olay dinleyicileri ekle
                    document.querySelectorAll('.delete-btn').forEach(button => {
                        button.addEventListener('click', function() {
                            const recordingId = this.getAttribute('data-id');
                            deleteRecording(recordingId);
                        });
                    });
                }
            })
            .catch(error => {
                console.error('Oturumlar yüklenemedi:', error);
                sessionsList.innerHTML = '<tr><td colspan="6" class="text-center">Hata: Oturumlar yüklenemedi.</td></tr>';
            });
    }
    
    // İzleme modalını aç
    function openPlaybackModal(recordingId) {
        // Sessions modalını kapat
        const sessionsModal = bootstrap.Modal.getInstance(document.getElementById('sessionsModal'));
        sessionsModal.hide();
        
        // İzleme modalını aç
        const playbackModal = new bootstrap.Modal(document.getElementById('playbackModal'));
        playbackModal.show();
        
        // İzleme terminalini başlat
        const term = initPlaybackTerminal();
        
        // Kayıt verilerini yükle
        fetch(`/api/terminal/recordings/${recordingId}`)
            .then(response => response.json())
            .then(data => {
                // Kayıt verilerini sakla
                playbackData = data.events;
                playbackIndex = 0;
                
                // Meta verileri görüntüle
                const startTime = new Date(data.metadata.start_time);
                document.getElementById('playbackModalLabel').textContent = `${data.metadata.target} - ${startTime.toLocaleString()}`;
                
                // İndir ve sil düğmelerini yapılandır
                document.getElementById('downloadRecordingBtn').setAttribute('data-id', recordingId);
                document.getElementById('deleteRecordingBtn').setAttribute('data-id', recordingId);
                
                // İlerleme çubuğunu sıfırla
                updatePlaybackProgress(0);
                
                // Oynat düğmesini etkinleştir
                document.getElementById('playBtn').disabled = false;
                document.getElementById('pauseBtn').disabled = true;
                document.getElementById('stopBtn').disabled = true;
            })
            .catch(error => {
                console.error('Kayıt verisi yüklenemedi:', error);
                term.writeln('Hata: Kayıt verisi yüklenemedi.');
            });
    });
    
    // Oynat düğmesi
    document.getElementById('playBtn').addEventListener('click', function() {
        if (playbackData.length === 0) return;
        
        // Düğme durumlarını güncelle
        this.disabled = true;
        document.getElementById('pauseBtn').disabled = false;
        document.getElementById('stopBtn').disabled = false;
        
        // Oynatma hızını al
        const speed = parseFloat(document.getElementById('playbackSpeed').value);
        
        // İzleme için interval oluştur
        playbackInterval = setInterval(() => {
            if (playbackIndex >= playbackData.length) {
                // İzleme tamamlandı
                clearInterval(playbackInterval);
                document.getElementById('playBtn').disabled = false;
                document.getElementById('pauseBtn').disabled = true;
                document.getElementById('stopBtn').disabled = true;
                updatePlaybackProgress(100);
                return;
            }
            
            // Veriyi al ve işle
            const event = playbackData[playbackIndex];
            if (event.type === 'output') {
                playbackTerminal.write(event.data);
            }
            
            // İlerleme çubuğunu güncelle
            updatePlaybackProgress(Math.round((playbackIndex + 1) * 100 / playbackData.length));
            
            // Sonraki veri
            playbackIndex++;
        }, 100 / speed); // Hız ayarı
    });
    
    // Duraklat düğmesi
    document.getElementById('pauseBtn').addEventListener('click', function() {
        clearInterval(playbackInterval);
        
        // Düğme durumlarını güncelle
        this.disabled = true;
        document.getElementById('playBtn').disabled = false;
        document.getElementById('stopBtn').disabled = false;
    });
    
    // Durdur düğmesi
    document.getElementById('stopBtn').addEventListener('click', function() {
        clearInterval(playbackInterval);
        
        // İzlemeyi sıfırla
        playbackIndex = 0;
        playbackTerminal.clear();
        updatePlaybackProgress(0);
        
        // Düğme durumlarını güncelle
        this.disabled = true;
        document.getElementById('pauseBtn').disabled = true;
        document.getElementById('playBtn').disabled = false;
    });
    
    // İlerleme çubuğunu güncelle
    function updatePlaybackProgress(percent) {
        const progressBar = document.getElementById('playbackProgress');
        progressBar.style.width = percent + '%';
        progressBar.setAttribute('aria-valuenow', percent);
        progressBar.textContent = percent + '%';
    }
    
    // Kayıt indir
    document.getElementById('downloadRecordingBtn').addEventListener('click', function() {
        const recordingId = this.getAttribute('data-id');
        
        fetch(`/api/terminal/recordings/${recordingId}`)
            .then(response => response.json())
            .then(data => {
                // Verileri JSON dosyasına dönüştür
                const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(data, null, 2));
                
                // İndirme bağlantısı oluştur
                const downloadAnchorNode = document.createElement('a');
                downloadAnchorNode.setAttribute("href", dataStr);
                downloadAnchorNode.setAttribute("download", `terminal_recording_${recordingId}.json`);
                document.body.appendChild(downloadAnchorNode); // Firefox için gerekli
                downloadAnchorNode.click();
                downloadAnchorNode.remove();
            })
            .catch(error => {
                console.error('Kayıt indirilemedi:', error);
                alert('Kayıt indirilemedi: ' + error);
            });
    });
    
    // Kayıt sil
    document.getElementById('deleteRecordingBtn').addEventListener('click', function() {
        const recordingId = this.getAttribute('data-id');
        
        if (confirm('Bu kaydı silmek istediğinizden emin misiniz?')) {
            fetch(`/api/terminal/recordings/${recordingId}`, {
                method: 'DELETE'
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        // Modali kapat
                        const playbackModal = bootstrap.Modal.getInstance(document.getElementById('playbackModal'));
                        playbackModal.hide();
                        
                        // Sessions listesini yenile
                        loadSessions();
                        
                        // Sessions modalını aç
                        const sessionsModal = new bootstrap.Modal(document.getElementById('sessionsModal'));
                        sessionsModal.show();
                        
                        showToast('Kayıt başarıyla silindi');
                    } else {
                        showToast('Hata: ' + data.error, 'error');
                    }
                })
                .catch(error => {
                    console.error('Kayıt silinemedi:', error);
                    showToast('Kayıt silinemedi: ' + error, 'error');
                });
        }
    });
    
    // Toast bildirim göster
    function showToast(message, type = 'success') {
        // Toast container'ı kontrol et
        let toastContainer = document.getElementById('toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'toast-container';
            toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            document.body.appendChild(toastContainer);
        }
        
        // Unique ID oluştur
        const toastId = 'toast-' + Date.now();
        
        // Toast HTML'i
        const toastHtml = `
            <div id="${toastId}" class="toast" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="toast-header ${type === 'error' ? 'bg-danger text-white' : 'bg-success text-white'}">
                    <strong class="me-auto">${type === 'error' ? 'Hata' : 'Bilgi'}</strong>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast" aria-label="Kapat"></button>
                </div>
                <div class="toast-body">
                    ${message}
                </div>
            </div>
        `;
        
        // Toast'u container'a ekle
        toastContainer.insertAdjacentHTML('beforeend', toastHtml);
        
        // Toast'u görüntüle
        const toastElement = document.getElementById(toastId);
        const toast = new bootstrap.Toast(toastElement, { autohide: true, delay: 3000 });
        toast.show();
    }
    
    // Sayfa yüklendiğinde container listesini yükle
    loadContainers();
    
    // Dil desteği için
    document.addEventListener('translationsLoaded', function(e) {
        const translations = e.detail.translations;
        
        // Terminal sayfası için özel çeviriler
        document.querySelectorAll('[data-i18n]').forEach(element => {
            const key = element.getAttribute('data-i18n');
            if (translations[key]) {
                element.textContent = translations[key];
            }
        });
    });
}); 