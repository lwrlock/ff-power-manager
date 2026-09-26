# FF Power Manager

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux%20%2F%20Fedora-teal.svg)](https://getfedora.org)
[![Desktop: GNOME](https://img.shields.io/badge/Desktop-GNOME%20%2F%20Wayland-orange.svg)](https://www.gnome.org)
[![Engine: C & x86_64 ASM](https://img.shields.io/badge/Engine-C%20%26%20ASM-success.svg)](#)
[![Developed with AI](https://img.shields.io/badge/Developed%20with-AI%20Assistance-blueviolet.svg)](#-yapay-zekâ-desteğiyle-geliştirildi-ai-assisted)

[ [English](README.md) | Türkçe ]

Linux (Fedora / GNOME / Wayland) için geliştirilmiş **C ve x86_64 Assembly** motoruyla çalışan, ultra-hafif, sıfır gecikmeli güç yöneticisi ve Lenovo ToF insan varlığı algılama aracı.

Test Edilen Donanım: **Lenovo IdeaPad Pro 5 14IAH10 / Yoga Pro** (Intel Core Ultra 9 285H Arrow Lake, Intel Arc Graphics, Samsung 2.8K 120Hz OLED, 87 Wh batarya).

---

## 🌟 Öne Çıkan Yetenekler ve Yenilikler

- **⚡ C & x86_64 Assembly Motoru (%0.0 CPU Yükü, < 1 MB RAM):** Doğrudan Linux çekirdek çağrıları (syscall) ve el ile optimize edilmiş montaj (assembly) kodlarıyla sensör paketlerini alt-mikrosaniyede çözer; arka planda sıfır işlemci yüküyle çalışır.
- **🔋 Boşta ~5W Tüketim Optimizasyonu (Windows Seviyesi Pil Tasarrufu):**
  - **Derin C-State Desteği (Package C8/C10):** Intel LPSS PCI köprüleri optimize edilerek işlemci çipsetinin derin uykuya geçmesi sağlandı.
  - **Intel Arc GPU GuC SLPC Güç Tasarrufu:** GPU boşta `power_saving` moduna alınarak saat frekansı ve render standby (RC6) derin uykusu serbest bırakıldı.
  - **TUI & Panel Self Refresh (PSR):** Terminal arayüzü GPU çizim yükünü azaltarak panelin PSR modunda kalmasını sağlar.
  - **Gelişmiş Çekirdek & I/O Zamanlayıcıları:** `laptop_mode=5`, `dirty_writeback_centisecs=6000`, `nmi_watchdog=0`, SCSI ALPM `med_power_with_dipm` ve WiFi 802.11 güç tasarrufu.
- **📡 Canlı ToF Radarı ve Milimetre Hassasiyeti:** ST VL53L1 kızılötesi uçuş süresi (ToF) sensörünün 35 baytlık ham HID paketlerini doğrudan dinler. Mesafeyi 16-bit milimetre hassasiyetiyle anlık ölçer (`70 cm / 120 cm`). Masadan kalkıldığında ekran kararır, dönüldüğünde anında açılır.
- **🖥️ Dinamik 60 Hz / 120 Hz + VRR Geçişi:** Bataryaya geçildiğinde Samsung 2.8K OLED ekran otomatik olarak **60 Hz** moduna alınarak ~2W tasarruf sağlanır; şarja takıldığında **120 Hz + VRR** moduna geri döner.
- **🛡️ GNOME Arayüz Koruması:** GNOME'un arayüzde donma ve gecikmelere yol açan `power-saver` modunu dengeli tutarak her koşulda 60 FPS akıcılık sağlar.
- **📊 btop Tarzı Dinamik Terminal Dashboard (`ff-tui`):** Çok sekmeli (`[1] Overview`, `[2] Battery`, `[3] AC Power`), tek tuşla donanımda doğrulanan profil uygulama özellikli interaktif terminal arayüzü.
- **🎨 Modern GTK4 / Libadwaita Masaüstü Uygulaması (`ff-power-manager`):** Canlı ToF radarı, dinamik ilerleme çubuğu, tek tıkla doğrudan terminal paneli başlatma ve şık hero kart tasarımı.
- **🚀 Masaüstü Menü Entegrasyonu:** TUI paneli Fedora uygulama menüsünden (`Super` tuşu > **FF Power Manager (Terminal Paneli)**) doğrudan açılabilir.
- **⚙️ Tam Sistem Başlangıç Entegrasyonu (Autostart):** `systemd` servisleri ile bilgisayar açıldığında arka planda otomatik başlar.
- **🔒 Güvenli ve Hızlı Yetkilendirme:** `setuid root (4755)` korumalı `ffctl` ve Polkit kuralları sayesinde şifre sormadan anında donanım yazmaçlarını günceller.

---

## 🚀 Kurulum ve Başlatma

Terminalde depoyu derleyip kurmak için tek bir komut yeterlidir:

```bash
cd ff-power-manager
sudo ./install.sh
```

Kurulum tamamlandığında tüm sistem servisleri, yetkilendirme kuralları ve masaüstü kısayolları otomatik devreye girer.

---

## 🛠️ Kullanım Araçları

### 1. Dinamik Terminal Arayüzü (`ff-tui` veya `ffctl tui`)
Uygulama menüsünden *"FF Power Manager (Terminal Paneli)"* ikonuna tıklayabilir veya terminalde çalıştırabilirsiniz:
```bash
ff-tui
```
* `1` / `2` / `3` veya `Tab` : Sekmeler arasında geçiş (Genel Bakış / Batarya / Şebeke Gücü)
* `P` : ToF Varlık Sensörünü Canlı Aç / Kapat
* `T` : Intel Turbo Boost Aç / Kapat (Donanımda doğrulanır)
* `A` / `B` / `C` : Aktif sekmedeki profili anında donanıma uygula
* `Q` : Çıkış

### 2. Yüksek Hızlı CLI Aracı (`ffctl`)
```bash
# Donanım, batarya, EPP ve ToF durumunu anında görüntüle (< 1 ms)
ffctl status

# Canlı ToF sensör telemetrisini ve mesafeyi terminale akıt
ffctl sensor live

# ToF sensör durumunu ve alınan paket sayısını gör
ffctl sensor status

# Güç profilini doğrudan donanıma uygula ve doğrula
ffctl apply battery
ffctl apply ac
```

### 3. Modern Grafik Arayüzü (GTK4 / Libadwaita)
Uygulama menüsünden **FF Power Manager**'ı açabilir veya terminalden `ff-power-manager` komutunu verebilirsiniz.

---

## 🤖 Yapay Zekâ Desteğiyle Geliştirildi (AI-Assisted)

Bu proje; mimari tasarım, düşük seviyeli donanım optimizasyonları ve kullanıcı deneyimi süreçlerinde yapay zekâ (Google DeepMind Antigravity) ortaklığı ve mühendislik desteği ile geliştirilmiştir:

- **Tersine Mühendislik & Protokol Ayrıştırma:** ST VL53L1 ToF sensörünün ham 35 baytlık USB HID paket yapısının analizi ve 16-bit milimetre mesafe formatının çözülmesi.
- **x86_64 Assembly & C Çekirdeği:** Sıfır CPU tüketimiyle çalışan, mikro-saniye seviyesinde sysfs ve HID paket ayrıştırıcı rutinlerinin yazılması.
- **Güç Optimizasyonu (~5W Boşta):** Intel Core Ultra Arrow Lake işlemci mimarisinin Package C-State (C8/C10) engellerinin tespiti, Intel Arc GPU GuC SLPC güç tasarrufu ve 2.8K OLED ekran yenileme hızı otomasyonunun kurgulanması.
- **Arayüz Tasarımı:** GNOME ve Libadwaita standartlarına uygun modern GTK4 GUI ve btop esintili terminal TUI arayüzlerinin oluşturulması.

---

## 📄 Lisans

MIT Lisansı. Telif Hakkı (c) 2026 lwrlock. Ayrıntılar için [LICENSE](LICENSE) dosyasına bakabilirsiniz.

