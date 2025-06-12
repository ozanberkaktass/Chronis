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
        this.connectionUrl = null;
        this.statusIndicator = null;
        this.statusText = null;
        this.fontSize = 14;
        this.theme = 'dark';
        this.debugMode = true; // Hata ayıklama modunu etkinleştir
    }
    
    // Terminal yöneticisini başlat
    init() {
        // DOM elemanlarını al
        this.connectionUrl = document.getElementById('connection-url');
        this.statusIndicator = document.getElementById('status-indicator');
        this.statusText = document.getElementById('status-text');
        const terminalContainer = document.getElementById('terminal-container');
        
        // Terminal'i oluştur
        this.term = new Terminal({
            cursorBlink: true,
            theme: {
                background: '#000000',
                foreground: '#f0f0f0',
                cursor: '#ffffff',
                cursorAccent: '#000000',
                selection: 'rgba(255, 255, 255, 0.3)',
                black: '#000000',
                red: '#cc0000',
                green: '#4e9a06',
                yellow: '#c4a000',
                blue: '#3465a4',
                magenta: '#75507b',
                cyan: '#06989a',
                white: '#d3d7cf',
                brightBlack: '#555753',
                brightRed: '#ef2929',
                brightGreen: '#8ae234',
                brightYellow: '#fce94f',
                brightBlue: '#729fcf',
                brightMagenta: '#ad7fa8',
                brightCyan: '#34e2e2',
                brightWhite: '#eeeeec'
            },
            fontSize: this.fontSize,
            fontFamily: 'Consolas, "Courier New", monospace',
            lineHeight: 1.2,
            convertEol: true,
            scrollback: 5000,
            disableStdin: false
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
        this.showWelcomeMessage();
        
        this.resizeTerminal();
        this.setupUIListeners();
        
        this.log('Terminal2 yöneticisi başlatıldı');
    }
    
    // Hoş geldin mesajı göster
    showWelcomeMessage() {
        this.term.writeln('\x1B[1;34mChronis Terminal2\x1B[0m - Web Tabanlı SSH/Container Terminal');
        this.term.writeln('');
        this.term.writeln('Bir terminal oturumu başlatmak için sağ üstteki \x1B[1;32m+\x1B[0m butonuna tıklayın.');
        this.term.writeln('');
        this.term.writeln('\x1B[2mBağlantı bekleniyor...\x1B[0m');
        this.term.writeln('');
        this.term.write('\x1B[32mroot@localhost\x1B[0m:\x1B[34m~\x1B[0m$ ');
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
        
        // Pencere kontrolleri
        document.getElementById('btn-minimize').addEventListener('click', () => {
            this.log('Minimize button clicked');
            // Burada minimize işlevi eklenebilir
        });
        
        document.getElementById('btn-maximize').addEventListener('click', () => {
            this.toggleFullscreen();
        });
        
        document.getElementById('btn-close').addEventListener('click', () => {
            if (confirm('Terminal oturumunu kapatmak istediğinize emin misiniz?')) {
                window.location.href = '/dashboard';
            }
        });
        
        // Font boyutu kontrolleri
        document.getElementById('btn-font-size-decrease').addEventListener('click', () => {
            this.changeFontSize(-1);
        });
        
        document.getElementById('btn-font-size-increase').addEventListener('click', () => {
            this.changeFontSize(1);
        });
        
        // Tema değiştirme
        document.getElementById('btn-theme').addEventListener('click', () => {
            this.toggleTheme();
        });
        
        // Ayarlar butonu
        document.getElementById('btn-settings').addEventListener('click', () => {
            this.log('Settings button clicked');
            // Burada ayarlar menüsü gösterilebilir
        });
    }
    
    // Font boyutunu değiştir
    changeFontSize(delta) {
        this.fontSize = Math.max(10, Math.min(20, this.fontSize + delta));
        this.term.options.fontSize = this.fontSize;
        this.fitAddon.fit();
        this.log('Font boyutu değiştirildi:', this.fontSize);
    }
    
    // Temayı değiştir
    toggleTheme() {
        if (this.theme === 'dark') {
            this.theme = 'light';
            this.term.options.theme = {
                background: '#ffffff',
                foreground: '#000000',
                cursor: '#000000',
                cursorAccent: '#ffffff',
                selection: 'rgba(0, 0, 0, 0.3)',
                black: '#000000',
                red: '#cc0000',
                green: '#4e9a06',
                yellow: '#c4a000',
                blue: '#3465a4',
                magenta: '#75507b',
                cyan: '#06989a',
                white: '#d3d7cf',
                brightBlack: '#555753',
                brightRed: '#ef2929',
                brightGreen: '#8ae234',
                brightYellow: '#fce94f',
                brightBlue: '#729fcf',
                brightMagenta: '#ad7fa8',
                brightCyan: '#34e2e2',
                brightWhite: '#eeeeec'
            };
        } else {
            this.theme = 'dark';
            this.term.options.theme = {
                background: '#000000',
                foreground: '#f0f0f0',
                cursor: '#ffffff',
                cursorAccent: '#000000',
                selection: 'rgba(255, 255, 255, 0.3)',
                black: '#000000',
                red: '#cc0000',
                green: '#4e9a06',
                yellow: '#c4a000',
                blue: '#3465a4',
                magenta: '#75507b',
                cyan: '#06989a',
                white: '#d3d7cf',
                brightBlack: '#555753',
                brightRed: '#ef2929',
                brightGreen: '#8ae234',
                brightYellow: '#fce94f',
                brightBlue: '#729fcf',
                brightMagenta: '#ad7fa8',
                brightCyan: '#34e2e2',
                brightWhite: '#eeeeec'
            };
        }
        this.term.refresh();
        this.log('Tema değiştirildi:', this.theme);
    }
    
    // Tam ekran modunu aç/kapat
    toggleFullscreen() {
        const elem = document.documentElement;
        
        if (!document.fullscreenElement) {
            elem.requestFullscreen().catch(err => {
                this.logError(`Tam ekran hatası: ${err.message}`);
            });
        } else {
            document.exitFullscreen();
        }
    }
    
    // Socket.io olay işleyicileri
    handleConnect() {
        this.log('Socket.io bağlantısı kuruldu');
        this.term.writeln('\r\n\x1B[1;32mSocket.io bağlantısı kuruldu.\x1B[0m');
        this.updateStatus('connected', 'Socket.io bağlantısı kuruldu');
    }
    
    handleDisconnect() {
        this.log('Socket.io bağlantısı kesildi');
        this.term.writeln('\r\n\x1B[1;31mSocket.io bağlantısı kesildi. Sayfa yenilenmeli!\x1B[0m');
        this.activeSession = null;
        this.updateConnectionUrl('');
        this.updateStatus('disconnected', 'Bağlantı kesildi');
    }
    
    handleConnectError(error) {
        this.logError('Socket.io bağlantı hatası:', error);
        this.term.writeln(`\r\n\x1B[1;31mBağlantı hatası: ${error.message}\x1B[0m`);
        this.updateStatus('disconnected', `Bağlantı hatası: ${error.message}`);
    }
    
    handleTerminalOutput(data) {
        this.log('Terminal çıktısı alındı:', data.output ? data.output.length + ' bayt' : 'boş');
        if (data.output) {
            this.term.write(data.output);
        }
    }
    
    handleConnectionError(data) {
        this.logError('Terminal bağlantı hatası:', data);
        this.term.writeln(`\r\n\x1B[1;31mHata: ${data.error}\x1B[0m`);
        this.updateStatus('disconnected', `Hata: ${data.error}`);
    }
    
    handleSessionCreated(data) {
        this.log('Oturum oluşturuldu:', data);
        this.activeSession = data.session_id;
        
        // Modal'ı kapat
        const modal = bootstrap.Modal.getInstance(document.getElementById('newSessionModal'));
        if (modal) modal.hide();
        
        this.term.clear();
        this.term.writeln('\x1B[1;32mTerminal oturumu başlatıldı. Bağlantı kuruluyor...\x1B[0m');
        this.updateStatus('connected', 'Bağlantı kuruldu');
        
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
    
    // Durum göstergesini güncelle
    updateStatus(status, message) {
        if (this.statusIndicator) {
            this.statusIndicator.className = 'status-indicator ' + status;
        }
        
        if (this.statusText) {
            this.statusText.textContent = message || '';
        }
    }
    
    // Bağlantı URL'sini güncelle
    updateConnectionUrl(url) {
        if (!url) {
            this.connectionUrl.textContent = 'Bağlı değil';
            return;
        }
        this.connectionUrl.textContent = url;
    }
    
    // Terminal giriş olayı
    handleTerminalInput(data) {
        if (this.activeSession) {
            this.log('Terminal girişi gönderiliyor:', data.length + ' bayt');
            this.socket.emit('terminal_input', {
                session_id: this.activeSession,
                data: data
            });
        } else {
            // Demo modu - gerçek bağlantı olmadığında basit komutları taklit et
            if (data === '\r') {
                const input = this.term._core.buffer.active.getLine(this.term._core.buffer.active.baseY + this.term._core.buffer.active.cursorY).translateToString().trim().replace(/^.*\$ /, '');
                this.handleDemoCommand(input);
            } else {
                this.term.write(data);
            }
        }
    }
    
    // Demo modu - basit komutları taklit et
    handleDemoCommand(command) {
        this.term.writeln('');
        
        switch (command.toLowerCase()) {
            case 'help':
                this.term.writeln('Kullanılabilir komutlar:');
                this.term.writeln('  help     - Bu yardım mesajını göster');
                this.term.writeln('  clear    - Ekranı temizle');
                this.term.writeln('  ls       - Dosyaları listele');
                this.term.writeln('  date     - Tarih ve saati göster');
                this.term.writeln('  connect  - Bağlantı menüsünü aç');
                break;
                
            case 'clear':
                this.term.clear();
                break;
                
            case 'ls':
                this.term.writeln('index.html');
                this.term.writeln('style.css');
                this.term.writeln('app.js');
                this.term.writeln('README.md');
                this.term.writeln('package.json');
                break;
                
            case 'date':
                this.term.writeln(new Date().toString());
                break;
                
            case 'connect':
                const modal = new bootstrap.Modal(document.getElementById('newSessionModal'));
                modal.show();
                break;
                
            case '':
                // Boş komut, hiçbir şey yapma
                break;
                
            default:
                this.term.writeln(`Komut bulunamadı: ${command}`);
                this.term.writeln('Kullanılabilir komutları görmek için "help" yazın');
        }
        
        this.term.write('\r\n\x1B[32mroot@localhost\x1B[0m:\x1B[34m~\x1B[0m$ ');
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
            this.updateConnectionUrl(`ssh://${username}@${host}:${port}`);
            
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
            this.updateConnectionUrl(`container://${containerId.substring(0, 12)}`);
            
            this.socket.emit('create_session', {
                type: 'container',
                target: containerId
            });
        } else if (sessionType === 'host') {
            this.log('Yerel host bağlantısı başlatılıyor');
            this.updateConnectionUrl('local://host');
            
            this.socket.emit('create_session', {
                type: 'host'
            });
        }
        
        // Bağlantı kurulurken mesaj göster
        this.term.clear();
        this.term.writeln("\x1B[1;33mBağlantı kuruluyor, lütfen bekleyin...\x1B[0m");
        this.updateStatus('disconnected', 'Bağlantı kuruluyor...');
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