/**
 * Chronis - Docker Container Yönetim Uygulaması
 * main.js - Ana JavaScript dosyası
 */

document.addEventListener('DOMContentLoaded', function() {
    // Tooltips'leri başlat
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Çeviri olayını dinle
    document.addEventListener('translationsLoaded', function(e) {
        const translations = e.detail.translations;
        
        // Sayfalara özgü dinamik çevirileri uygula
        applyDynamicTranslations(translations);
    });
    
    // Dinamik içeriklere çevirileri uygulama fonksiyonu
    function applyDynamicTranslations(translations) {
        // Container tablosu başlıkları
        const containerStatusCol = document.querySelector('th[data-status-col]');
        if (containerStatusCol && translations.status) {
            containerStatusCol.textContent = translations.status;
        }
        
        // Çalışıyor/Durmuş gibi durum bilgileri
        const statusRunning = document.querySelectorAll('.status-badge.running');
        statusRunning.forEach(badge => {
            if (translations.running) {
                badge.textContent = translations.running;
            }
        });
        
        const statusStopped = document.querySelectorAll('.status-badge.exited');
        statusStopped.forEach(badge => {
            if (translations.stopped) {
                badge.textContent = translations.stopped;
            }
        });
        
        // Grafik etiketleri güncelleme
        const charts = window.charts || [];
        charts.forEach(chart => {
            if (chart.data && chart.data.datasets) {
                chart.data.datasets.forEach(dataset => {
                    if (dataset.originalLabel && translations[dataset.originalLabel]) {
                        dataset.label = translations[dataset.originalLabel];
                    }
                });
                chart.update();
            }
        });
    }

    // Container oluşturma işlemi
    const createContainerBtn = document.getElementById('createContainerBtn');
    if (createContainerBtn) {
        createContainerBtn.addEventListener('click', function() {
            const imageName = document.getElementById('imageName').value;
            const containerName = document.getElementById('containerName').value;
            const ports = document.getElementById('ports').value;
            const volumes = document.getElementById('volumes').value;
            const env = document.getElementById('env').value;
            const startAfterCreation = document.getElementById('startAfterCreation').checked;
            
            // Validasyon
            if (!imageName) {
                alert('Image ismi gereklidir');
                return;
            }
            
            // Form verilerini hazırla
            const formData = {
                image: imageName,
                name: containerName,
                ports: ports,
                volumes: volumes,
                env: env,
                start: startAfterCreation
            };
            
            // API isteği gönder
            fetch('/api/containers/create', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(formData),
            })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    alert('Hata: ' + data.error);
                } else {
                    // Modal'ı kapat ve sayfayı yenile
                    const modal = bootstrap.Modal.getInstance(document.getElementById('createContainerModal'));
                    modal.hide();
                    window.location.reload();
                }
            })
            .catch((error) => {
                console.error('Error:', error);
                alert('Bir hata oluştu: ' + error);
            });
        });
    }
    
    // Dashboard için istatistik güncelleme
    function updateStats() {
        const statsElements = document.querySelectorAll('[data-stat]');
        if (statsElements.length > 0) {
            fetch('/api/stats')
                .then(response => response.json())
                .then(data => {
                    statsElements.forEach(element => {
                        const statKey = element.getAttribute('data-stat');
                        if (statKey && data[statKey] !== undefined) {
                            element.textContent = data[statKey];
                        }
                    });
                })
                .catch(error => console.error('Stat güncelleme hatası:', error));
        }
    }
    
    // Her 30 saniyede bir istatistikleri güncelle
    if (document.querySelector('[data-stat]')) {
        setInterval(updateStats, 30000);
    }
    
    // Container filtreleme
    const statusFilter = document.getElementById('statusFilter');
    if (statusFilter) {
        statusFilter.addEventListener('change', function() {
            const selectedStatus = this.value;
            const rows = document.querySelectorAll('tbody tr');
            
            rows.forEach(row => {
                const statusCell = row.querySelector('td:nth-child(3)');
                
                if (selectedStatus === 'all' || statusCell.textContent.trim().toLowerCase().includes(selectedStatus)) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        });
    }
    
    // Container detayları için log güncelleme
    const logRefreshBtn = document.getElementById('refreshLogs');
    if (logRefreshBtn) {
        logRefreshBtn.addEventListener('click', function() {
            const containerId = this.getAttribute('data-container-id');
            if (containerId) {
                fetch(`/api/containers/${containerId}/logs`)
                    .then(response => response.text())
                    .then(logs => {
                        document.getElementById('containerLogs').textContent = logs;
                    })
                    .catch(error => console.error('Log güncelleme hatası:', error));
            }
        });
    }
    
    // Auto-refresh toggle
    const autoRefreshToggle = document.getElementById('autoRefreshToggle');
    if (autoRefreshToggle) {
        let autoRefreshInterval;
        
        autoRefreshToggle.addEventListener('change', function() {
            if (this.checked) {
                // Auto-refresh başlat
                autoRefreshInterval = setInterval(function() {
                    // Sayfayı yenile
                    window.location.reload();
                }, 10000); // 10 saniyede bir
            } else {
                // Auto-refresh durdur
                clearInterval(autoRefreshInterval);
            }
        });
    }
}); 