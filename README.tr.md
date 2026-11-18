# FF Power Manager v2.2

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Ubuntu | Debian | Fedora](https://img.shields.io/badge/Platform-Ubuntu%20%7C%20Debian%20%7C%20Fedora-teal.svg)](https://ubuntu.com)
[![Desktop: GNOME | Hyprland | Plasma](https://img.shields.io/badge/Desktop-GNOME%20%7C%20Hyprland%20%7C%20Plasma-orange.svg)](https://www.gnome.org)
[![Engine: C & x86_64 ASM](https://img.shields.io/badge/Engine-C%20%26%20x86__64%20ASM-success.svg)](#)
[![AI-Assisted: Antigravity](https://img.shields.io/badge/AI--Destekli-Google%20DeepMind%20Antigravity-purple.svg)](#geliştirme-ve-yapay-zeka-desteği)
[![Release: v2.2.0](https://img.shields.io/badge/Release-v2.2.0-blueviolet.svg)](https://github.com/lwrlock/ff-power-manager/releases/tag/v2.2.0)

[ [English](README.md) | Türkçe ]

**Linux dizüstü bilgisayarlar için düşük yük bindirmeyen güç yönetimi, Çoklu Masaüstü Adaptif Yenileme (`60↔Max Hz`), uyanma suçlusu analizi (`ffctl blame`), `s2idle` uyku tüketim raporu (`ffctl sleep-report`), ToF varlık radarı ve kozmik uzay temalı GTK4 kontrol merkezi.**

---

## v2.2.0 Yenilikleri

- **Kozmik Uzay Temalı GTK4 Masaüstü Uygulaması (`ff-power-manager`):** Mor nebula, dönen halkalı gezegen, yörünge uydusu ve kayan yıldızlar içeren Cairo uzay sahnesi üzerine kurulu buzlu cam arayüz (pildeyken otomatik ~9 FPS güç tasarrufu moduna geçer), **4'lü Hero Telemetri Kartları**, **Canlı Watt/Sıcaklık Grafiği** ve özel SVG uygulama ikonu.
- **Enerji & Uyandırma Suçlusu Analizi (`ffctl blame [--json]`):** 250 ms'de `/proc/[pid]` üzerinden CPU + context switch uyanmalarını ölçer, en çok güç tüketen süreçleri ve uykuya geçmemiş PCI/USB donanımları listeler (hem CLI hem GTK4 `Blame Profiler` sekmesi).
- **Gerçek Uyku Tüketim Raporu (`ffctl sleep-report [--json]`):** `ff-sleep-guard` her uykuda `Wh` ve `%` farkını kaydedip uyandıktan sonra ortalama bekleme tüketimini (`W` ve `%/saat`) raporlar.
- **Çoklu Masaüstü Adaptif Yenileme & Odak Kısma:** GNOME (`Mutter`), Hyprland (`hyprctl`) ve KDE Plasma (`kscreen-doctor`) üzerinde pilde `60↔Max Hz` geçişi + odak dışındaki ağır tarayıcıların yalnızca pilde öncelik kısılması.
- **Waybar Hazır Modülü & RPM Spec:** [contrib/waybar/](contrib/waybar/README.md) snippet'i ve Fedora `.rpm` paketi için [packaging/ff-power-manager.spec](packaging/ff-power-manager.spec).

---

## Kurulum (`.deb` veya Kaynaktan)

```bash
# 1. Ubuntu / Debian .deb paketi ile:
sudo apt install ./ff-power-manager_2.2.0_amd64.deb

# 2. Veya kaynaktan kurulum (Ubuntu / Debian / Fedora):
git clone https://github.com/lwrlock/ff-power-manager.git
cd ff-power-manager
sudo ./install.sh
```

## Geliştirme ve Yapay Zeka Desteği

**FF Power Manager**, **Furkan (`@lwrlock`)** tarafından **Google DeepMind Antigravity** yapay zeka destekli mühendislik iş birliği ile geliştirilmektedir (HID Report 4 çözümleme, C/x86_64 Assembly optimizasyonu, GTK4 Cairo görselleştirmesi, birim testleri ve çoklu dağıtım sertleştirmesi süreçlerinde AI desteği alınmış; tüm canlı donanım ve çekirdek testleri doğrudan gerçek Linux sistemler üzerinde doğrulanmıştır).

## Lisans

MIT Lisansı — Telif Hakkı (c) 2026 Furkan (**lwrlock**). Ayrıntılar için [LICENSE](LICENSE).
