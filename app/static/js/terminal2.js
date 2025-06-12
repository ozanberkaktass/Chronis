/**
 * Chronis - Terminal2 İşlevselliği
 * WebSocket tabanlı terminal iletişimi ve kayıt/oynatma işlemleri
 * Versiyon: 1.3
 */

// Terminal yöneticisi
class TerminalManager {
    constructor() {
        // Terminal özellikleri
        this.term = null;
        this.fitAddon = null;
        this.activeSession = null;
        this.socket = null;
        this.statusIndicator = null;
        this.connectionLabel = null;
        this.debugMode = true; // Hata ayıklama modunu etkinleştir
    }
    
    // Terminal yöneticisini başlat
    init() {
        // DOM elemanlarını al
        this.statusIndicator = document.getElementById('status-indicator');
        this.connectionLabel = document.getElementById('connection-label');
        const terminalContainer = document.getElementById('terminal-container');
        
        // Terminal'i oluştur
        this.term = new Terminal({
            cursorBlink: true,
            theme: {
                background: '#0f1419',
                foreground: '#f0f0f0'
            },
            fontSize: 14,
            fontFamily: 'Courier New, monospace',
            convertEol: true
        });
        
        // Terminal eklentileri
        this.fitAddon = new FitAddon.FitAddon();
        this.term.loadAddon(this.fitAddon);
        
        // Terminal'i başlat
        this.term.open(terminalContainer);
        this.fitAddon.fit();
        
        // xterm div'inin yüksekliğini ve genişliğini %100 yap
        const xtermDiv = terminalContainer.querySelector('.xterm');
        if (xtermDiv) {
            xtermDiv.style.height = '100%';
            xtermDiv.style.width = '100%';
        }
        
        // Socket.io bağlantısı
        this.socket = io('/terminal', {
            path: '/socket.io',
            transports: ['websocket'],
            upgrade: false,
            reconnection: true,
            reconnectionAttempts: 5,
            reconnectionDelay: 1000,
            forceNew: true
        });
        
        // Olay dinleyicileri
        this.bindEvents();
        
        // Sayfa yüklendiğinde hoş geldin mesajı
        this.term.writeln('Chronis Terminal2 Uygulamasına Hoş Geldiniz!');
        this.term.writeln('Bir terminal oturumu başlatmak için "Yeni Oturum" butonuna tıklayın.');
        
        this.resizeTerminal();
        this.setupUIListeners();
        
        this.log('Terminal yöneticisi başlatıldı');
    }
    
    // Terminal boyutunu ayarla
    resizeTerminal() {
        this.fitAddon.fit();
        if (this.activeSession) {
            const dimensions = {
                session_id: this.activeSession,
                cols: this.term.cols,
                rows: this.term.rows
            };
            this.socket.emit('terminal_resize', dimensions);
            this.log('Terminal boyutu güncellendi:', dimensions);
        }
    }
    
    // Olay dinleyicileri
    bindEvents() {
        // Socket.io olayları
        this.socket.on('connect', () => this.handleConnect());
        this.socket.on('disconnect', () => this.handleDisconnect());
        this.socket.on('connect_error', (error) => this.handleConnectError(error));
        this.socket.on('terminal_output', (data) => this.handleTerminalOutput(data));
        this.socket.on('connection_error', (data) => this.handleConnectionError(data));
        this.socket.on('session_created', (data) => this.handleSessionCreated(data));
        
        // Terminal olayları
        this.term.onData((data) => this.handleTerminalInput(data));
        
        // Pencere boyutu değiştiğinde terminal boyutunu güncelle
        window.addEventListener('resize', () => this.resizeTerminal());
    }
    
    // Arayüz olayları
    setupUIListeners() {
        // Yeni oturum butonu
        document.getElementById('btn-new-session').addEventListener('click', () => {
            const modal = new bootstrap.Modal(document.getElementById('newSessionModal'));
            modal.show();
        });
        
        // Bağlan butonu
        document.getElementById('btn-connect').addEventListener('click', () => this.connectToSession());
        
        // Session tipi değiştiğinde
        document.getElementById('session-type').addEventListener('change', (e) => {
            const type = e.target.value;
            document.getElementById('ssh-fields').style.display = (type === 'ssh') ? 'block' : 'none';
            document.getElementById('container-fields').style.display = (type === 'container') ? 'block' : 'none';
            document.getElementById('host-fields').style.display = (type === 'host') ? 'block' : 'none';
            
            if (type === 'container') {
                this.fetchContainers();
            }
        });
    }
    
    // Socket.io olay işleyicileri
    handleConnect() {
        this.log('Socket.io bağlantısı kuruldu');
        this.statusIndicator.classList.remove('status-disconnected');
        this.statusIndicator.classList.add('status-connected');
        this.connectionLabel.textContent = "Bağlandı";
        this.term.clear();
        this.term.writeln('Socket.io bağlantısı kuruldu. Terminal oturumu başlatmak için "Yeni Oturum" butonuna tıklayın.');
    }
    
    handleDisconnect() {
        this.log('Socket.io bağlantısı kesildi');
        this.statusIndicator.classList.remove('status-connected');
        this.statusIndicator.classList.add('status-disconnected');
        this.connectionLabel.textContent = "Bağlantı kesildi";
        this.term.writeln('\r\n\nSocket.io bağlantısı kesildi. Sayfa yenilenmeli!');
        this.activeSession = null;
    }
    
    handleConnectError(error) {
        this.logError('Socket.io bağlantı hatası:', error);
        this.term.writeln(`\r\nBağlantı hatası: ${error.message}`);
    }
    
    handleTerminalOutput(data) {
        this.log('Terminal çıktısı alındı:', data.output ? data.output.length + ' bayt' : 'boş');
        if (data.output) {
            this.term.write(data.output);
        }
    }
    
    handleConnectionError(data) {
        this.logError('Terminal bağlantı hatası:', data);
        this.term.writeln(`\r\n\nHata: ${data.error}`);
    }
    
    handleSessionCreated(data) {
        this.log('Oturum oluşturuldu:', data);
        this.activeSession = data.session_id;
        
        // Modal'ı kapat
        const modal = bootstrap.Modal.getInstance(document.getElementById('newSessionModal'));
        if (modal) modal.hide();
        
        this.term.clear();
        this.term.writeln('Terminal oturumu başlatıldı. Bağlantı kuruluyor...');
        
        // Oturum oluşturulduktan sonra terminal boyutunu ayarla
        setTimeout(() => {
            this.resizeTerminal();
            // Bazı SSH sunucuları için başlangıçta Enter tuşuna basma
            this.socket.emit('terminal_input', {
                session_id: this.activeSession,
                data: "\r\n"
            });
        }, 500);
    }
    
    // Terminal giriş olayı
    handleTerminalInput(data) {
        if (this.activeSession) {
            this.log('Terminal girişi gönderiliyor:', data.length + ' bayt');
            this.socket.emit('terminal_input', {
                session_id: this.activeSession,
                data: data
            });
        }
    }
    
    // Oturum bağlantı işlemi
    connectToSession() {
        const sessionType = document.getElementById('session-type').value;
        
        if (sessionType === 'ssh') {
            const host = document.getElementById('ssh-host').value;
            const port = document.getElementById('ssh-port').value;
            const username = document.getElementById('ssh-username').value;
            const password = document.getElementById('ssh-password').value;
            
            if (!host || !username || !password) {
                alert("Lütfen gerekli tüm alanları doldurun");
                return;
            }
            
            this.log('SSH bağlantısı başlatılıyor:', host, port, username);
            this.socket.emit('create_session', {
                type: 'ssh',
                host: host,
                port: port,
                username: username,
                password: password
            });
        } else if (sessionType === 'container') {
            const containerId = document.getElementById('container-id').value;
            
            if (!containerId) {
                alert("Lütfen bir konteyner seçin");
                return;
            }
            
            this.log('Konteyner bağlantısı başlatılıyor:', containerId);
            this.socket.emit('create_session', {
                type: 'container',
                target: containerId
            });
        } else if (sessionType === 'host') {
            this.log('Yerel host bağlantısı başlatılıyor');
            this.socket.emit('create_session', {
                type: 'host'
            });
        }
        
        // Bağlantı kurulurken mesaj göster
        this.term.clear();
        this.term.writeln("Bağlantı kuruluyor, lütfen bekleyin...");
    }
    
    // Konteynerleri getir
    fetchContainers() {
        fetch('/api/containers')
            .then(response => response.json())
            .then(data => {
                const containerSelect = document.getElementById('container-id');
                containerSelect.innerHTML = '';
                
                if (data.containers && data.containers.length > 0) {
                    data.containers.forEach(container => {
                        if (container.status === 'running') {
                            const option = document.createElement('option');
                            option.value = container.id;
                            option.textContent = `${container.name} (${container.id.substring(0, 12)})`;
                            containerSelect.appendChild(option);
                        }
                    });
                } else {
                    const option = document.createElement('option');
                    option.value = '';
                    option.textContent = 'Çalışan konteyner bulunamadı';
                    containerSelect.appendChild(option);
                }
            })
            .catch(error => {
                this.logError('Konteyner listesi alınamadı:', error);
                const containerSelect = document.getElementById('container-id');
                containerSelect.innerHTML = '<option value="">Hata: Konteynerler yüklenemedi</option>';
            });
    }
    
    // Loglama fonksiyonları
    log(...args) {
        if (this.debugMode) {
            console.log('[Terminal2]', ...args);
        }
    }
    
    logError(...args) {
        console.error('[Terminal2]', ...args);
    }
}

// Sayfa yüklendiğinde terminal yöneticisini başlat
document.addEventListener('DOMContentLoaded', () => {
    const terminalManager = new TerminalManager();
    terminalManager.init();
}); 