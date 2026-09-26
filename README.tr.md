# FF Power Manager

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux%20%2F%20Fedora-teal.svg)](https://getfedora.org)
[![Desktop: GNOME](https://img.shields.io/badge/Desktop-GNOME%20%2F%20Wayland-orange.svg)](https://www.gnome.org)
[![Engine: C & x86_64 ASM](https://img.shields.io/badge/Engine-C%20%26%20ASM-success.svg)](#)

[ [English](README.md) | Türkçe ]

Linux (Fedora / GNOME / Wayland) için geliştirilmiş **C & x86_64 Assembly** tabanlı ultra-hafif güç yöneticisi ve Lenovo ToF insan varlığı algılama aracı.

Test edilen donanım: **Lenovo IdeaPad Pro 5 14IAH10 / Yoga Pro** (Intel Core Ultra 9 285H, Samsung 2.8K 120Hz OLED, 87 Wh batarya).

---

## Öne Çıkan Özellikler

- **C & x86_64 Assembly Çekirdeği (0.0% CPU Yükü):** Doğrudan Linux syscall'ları ve el ile yazılmış assembly rutinleriyle donanımdan veri okur; işlemci tüketmez, RAM kullanımı 1 MB'ın altındadır.
- **Canlı ToF Radarı ve Varlık Algılama:** ST VL53L1 kızılötesi sensöründen doğrudan HID paketlerini dinler. Ekrana olan mesafenizi canlı santimetre (örn. `68 cm / 120 cm`) olarak takip eder. Masadan kalktığınızda (> 1.2m) ekranı karartır, oturduğunuz anda anında uyandırır.
- **Otomatik 60 Hz / 120 Hz + VRR Geçişi:** Pildeyken Samsung 2.8K OLED paneli **60 Hz**'e çeker; şarja takıldığında otomatik olarak **120 Hz + VRR** moduna döndürür.
- **GNOME Kasma Koruması:** Batarya modundayken GNOME'un CPU'yu 400 MHz'e düşüren ve arayüzü kasan `power-saver` profiline girmesini engeller; daima `balanced` tutarak 60 FPS akıcılık sağlar.
- **btop Tarzı Dinamik TUI Dashboard (`ff-tui`):** Otomatik boyutlanan, 3 ayrı sekmeli (`[1] Overview`, `[2] Battery`, `[3] AC Power`), tek tuşla donanımda doğrulanan profil uygulama özellikli terminal arayüzü.
- **Açılışta Otomatik Başlama (Autostart):** `systemd` servisleri ile bilgisayar açıldığında hiçbir terminal komutuna gerek kalmadan arka planda çalışmaya başlar.

---

## Kurulum ve Başlatma

```bash
cd ff-power-manager
sudo ./install.sh
```

Kurulum tamamlandığında tüm servisler arka planda otomatik devreye girer.

---

## Kullanım Araçları

### 1. Canlı Terminal Arayüzü (`ff-tui` veya `ffctl tui`)
```bash
ff-tui
```
* `1` / `2` / `3` veya `Tab` : Sekmeler arasında geçiş (Overview / Battery / AC Power)
* `P` : ToF Sensörünü Canlı Aç / Kapat
* `T` : Intel Turbo Boost Aç / Kapat (Donanımda doğrulanır)
* `A` / `B` / `C` : Aktif sekmedeki profili anında uygula ve doğrula
* `Q` : Çıkış

### 2. Hızlı CLI Durum ve Telemetri (`ffctl`)
```bash
# Donanım, batarya ve ekran durumunu görüntüle (< 1 ms)
ffctl status

# Canlı ToF sensör telemetrisini ve mesafeyi terminale akıt
ffctl sensor live

# ToF sensör durumunu ve alınan paket sayısını gör
ffctl sensor status

# Güç profili uygula ve donanımda doğrula
ffctl apply battery
ffctl apply ac
```

### 3. Masaüstü Grafik Arayüzü (GTK4 / Libadwaita)
Uygulama menüsünden **FF Power Manager**'ı seçebilir veya terminalden `ff-power-manager` çalıştırabilirsiniz.

---

## Lisans

MIT Lisansı. Telif Hakkı (c) 2026 lwrlock. Ayrıntılar için [LICENSE](LICENSE) dosyasına bakabilirsiniz.
