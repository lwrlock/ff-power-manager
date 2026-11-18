# FF Power Manager v2.1

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Ubuntu | Debian | Fedora](https://img.shields.io/badge/Platform-Ubuntu%20%7C%20Debian%20%7C%20Fedora-teal.svg)](https://ubuntu.com)
[![Desktop: GNOME Wayland](https://img.shields.io/badge/Desktop-GNOME%20%2F%20Wayland-orange.svg)](https://www.gnome.org)
[![Engine: C & x86_64 ASM](https://img.shields.io/badge/Engine-C%20%26%20x86__64%20ASM-success.svg)](#)
[![AI-Assisted: Antigravity](https://img.shields.io/badge/AI--Destekli-Google%20DeepMind%20Antigravity-purple.svg)](#geliştirme-ve-yapay-zeka-desteği)
[![Release: v2.1.0](https://img.shields.io/badge/Release-v2.1.0-blueviolet.svg)](https://github.com/lwrlock/ff-power-manager/releases/tag/v2.1.0)

[ [English](README.md) | Türkçe ]

**Linux dizüstü bilgisayarlar için düşük yük bindirmeyen güç yönetimi, adaptif ekran tazeleme (`60↔Max Hz`), OLED yanık koruması, ToF varlık radarı, `ffctl doctor` donanım denetimi ve `s2idle` çanta koruması.**

**C & x86_64 Assembly** çekirdek motoru (`ffctl`, `ff-tui`, `ff-presence-sensor`) ve **Python / GTK4 / GNOME Shell Wayland** entegrasyonuyla Intel ve AMD dizüstü bilgisayarlarda (`Ubuntu`, `Debian`, `Fedora`) **evrensel donanım keşfi** ile çalışır.

---

## v2.1.0 Yenilikleri

- **`ffctl doctor` Donanım Denetimi ve `--json` Çıktısı:** `s2idle`/`deep` uyku korumasını, `/proc/acpi/wakeup` uyandırma kaynaklarını, PCI Runtime PM (`suspended`/`active`) oranını ve çakışan servisleri (`tlp`, `auto-cpufreq`) milisaniyenin altında denetler; `ffctl status/health/doctor --json` çıktılarını scriptler ve Waybar için üretir.
- **Güvenli Yetkilendirme (Zero Setuid Root):** `ffctl` ve `ff-tui` artık `0755` unprivileged çalışır; donanım yazma işlemleri `fork()` + `execv()` üzerinden scoped PolicyKit (`ff-power-helper`) ile yapılır (`sudo` ve `wheel` gruplarının ikisini de destekler).
- **Evrensel CPU/GPU/RAPL Kalibrasyonu:** `set_hybrid_topology()`, `pin_interactive_irqs()` ve `optimize_desktop_responsiveness()` gerçek `detect_cpu_topology()` çekirdeklerini, `cpuinfo_max_freq` tavanını ve RAPL `constraint_0_max_power_uw` limitini dinamik keşfeder; AMD Ryzen ve `amd-pstate-epp` sistemlerde de sorunsuz çalışır.
- **Gerçek Sıcaklık & Termal Güvenlik:** `hwmon` (`coretemp`/`k10temp`/`zenpower`) ve `thermal_zone` (`x86_pkg_temp`/`TCPU`) üzerinden gerçek CPU paket sıcaklığını okur; ağır yük `>=90°C` olduğunda PL1 limitini yumuşatır.
- **Pilde Adaptif Yenileme (`60 ↔ 120/144/165 Hz`):** Yalnızca pildeyken `8` saniye hareketsizlikte ekranı `60 Hz`'e alır; dokunduğun anda `Mutter.IdleMonitor.AddUserActiveWatch` ile gecikmesiz maksimum tazeleme hızına çıkar.
- **`s2idle` Çanta Koruması & 1 Kerelik `%100` Şarj Bekçisi:** Uykuya geçerken USB/Thunderbolt wake sinyallerini kapatır; yolculuk öncesi açılan `%100` şarj dolunca otomatik `%80` pil korumasını geri açar.

---

## Kurulum (`.deb` veya Kaynaktan)

```bash
# 1. Ubuntu / Debian .deb paketi ile:
sudo apt install ./ff-power-manager_2.1.0_amd64.deb

# 2. Veya kaynaktan kurulum (Ubuntu / Debian / Fedora):
git clone https://github.com/lwrlock/ff-power-manager.git
cd ff-power-manager
sudo ./install.sh
```

## Geliştirme ve Yapay Zeka Desteği

**FF Power Manager**, **Furkan (`@lwrlock`)** tarafından **Google DeepMind Antigravity** yapay zeka destekli mühendislik iş birliği ile geliştirilmektedir (HID Report 4 çözümleme, C/x86_64 Assembly optimizasyonu, birim testleri ve çoklu dağıtım sertleştirmesi süreçlerinde AI desteği alınmış; tüm canlı donanım ve çekirdek testleri doğrudan gerçek Linux sistemler üzerinde doğrulanmıştır).

## Lisans

MIT Lisansı — Telif Hakkı (c) 2026 Furkan (**lwrlock**). Ayrıntılar için [LICENSE](LICENSE).
