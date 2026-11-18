# FF Power Manager v2.0

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/lwrlock/ff-power-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/lwrlock/ff-power-manager/actions/workflows/ci.yml)
[![Platform: Ubuntu & Fedora](https://img.shields.io/badge/Platform-Ubuntu%20%7C%20Fedora-teal.svg)](https://ubuntu.com)
[![Desktop: GNOME Wayland](https://img.shields.io/badge/Desktop-GNOME%20%2F%20Wayland-orange.svg)](https://www.gnome.org)
[![Release: v2.0.0](https://img.shields.io/badge/Release-v2.0.0-blueviolet.svg)](https://github.com/lwrlock/ff-power-manager/releases/tag/v2.0.0)

[ [English](README.md) | Türkçe ]

**Linux dizüstü bilgisayarlara MacBook Pro pil ömrü, pilde 0 ms ProMotion (`60↔120 Hz`), OLED Yanık Koruması, ToF İnsan Varlığı Radarı ve `s2idle` Çanta Pil Koruması kazandıran akıllı güç yönetim paketi.**

**C & x86_64 Assembly** çekirdek motoru + **Python / GTK4 / GNOME Shell Wayland** entegrasyonuyla artık tüm Intel ve AMD dizüstü bilgisayarlarda (`Ubuntu`, `Debian`, `Fedora`) **otomatik donanım keşfi** ile çalışır.

---

## v2.0.0 Yenilikleri

- **Pilde Gerçek ProMotion (`60 ↔ 120/144/165 Hz`):** Yalnızca pildeyken (prizde veya sinema oynatımı sırasında değil) `8` saniye hareketsizlikte ekranı `60 Hz`'e alır; touchpad veya tuşa dokunduğun milisaniyede `Mutter.IdleMonitor` ile **0 ms'de** tekrar en yüksek tazeleme hızına çıkar.
- **Evrensel Donanım Keşfi:** CPU P/E/LP-E çekirdek topolojisi (`detect_cpu_topology()`), aktif ekran çözünürlüğü/Hz, `BAT0/BAT1` pil düğümü, Lenovo `conservation_mode` veya `charge_control_end_threshold`, Intel Xe / i915 / AMD Radeon GPU saat hızları ve SSD/Wi-Fi sıcaklıkları otomatik keşfedilir.
- **Sinema & Ders/Odak Bağlam Motoru:** `stremio`, `mpv`, `vlc` algılandığında otomatik `120 Hz` + gerçek renk (Gece Işığı geçici kapalı) devreye girer. Menüdeki **Ders / Odak Modu** tek tıkla Rahatsız Etme + Gece Işığı + sessiz profili açar.
- **1 Kerelik `%100` Şarj Bekçisi:** Günlük `%80` pil korumasını bozmadan yola çıkmadan önce tek tıkla `%100`'e şarj eder, `%99` olunca otomatik `%80` korumayı geri açıp bildirim gönderir.
- **Termal Güvenlik Kalkanı (`>=90°C`):** `auto_boost.py` ağır yüklerde paket sıcaklığını izler, `90°C` üstünde PL1 limitini yumuşatarak throttling'i ve aşırı fan sesini önler.
- **`s2idle` Çanta Koruması (`/lib/systemd/system-sleep/ff-sleep-guard`):** Uykuya geçerken USB/Thunderbolt wake sinyallerini kapatıp çantada ısınma ve şarj erimesini engeller.
- **Günlük OLED & Enerji Tasarruf Karnesi:** Üst menüde ToF radar ve ProMotion ile kazanılan ekran koruma dakikasını ve tahmini `Wh` tasarrufunu gösterir.

---

## Kurulum (`.deb` veya Kaynaktan)

```bash
# 1. Ubuntu / Debian .deb paketi ile:
sudo apt install ./ff-power-manager_2.0.0_amd64.deb

# 2. Veya kaynaktan kurulum (Ubuntu / Fedora):
git clone https://github.com/lwrlock/ff-power-manager.git
cd ff-power-manager
sudo ./install.sh
```

## Lisans

MIT Lisansı — Telif Hakkı (c) 2026 Furkan (**lwrlock**). Ayrıntılar için [LICENSE](LICENSE).
