# FF Power Manager

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux%20%2F%20Fedora-teal.svg)](https://getfedora.org)
[![Desktop: GNOME](https://img.shields.io/badge/Desktop-GNOME%20%2F%20Wayland-orange.svg)](https://www.gnome.org)

[ [English](README.md) | Türkçe ]

Linux (Fedora / GNOME / Wayland) için geliştirilmiş hafif güç profili yöneticisi ve Lenovo ToF insan varlığı algılama aracı.

Test edilen donanım: **Lenovo IdeaPad Pro 5 14IAH10** (Intel Core Ultra 9 285H, Samsung 2.8K 120Hz OLED, 87 Wh batarya).

---

## Özellikler

- **Dinamik OLED Yenileme Hızı:** Pildeyken ekranı kesintisiz **60 Hz**'e çeker; şarja takıldığında otomatik olarak **120 Hz + VRR** moduna döndürür.
- **Lenovo ToF Varlık Algılama:** Intel ISH (`8087:0AC2`) içindeki ST VL53L1 kızılötesi sensöründen doğrudan HID paketlerini dinler. Masadan kalktığınızda OLED ekranı karartır, döndüğünüz anda anında uyandırır. Kamera kullanılmaz; tamamen donanımsal mesafe ölçümüdür, %100 çevrimdışı ve güvenlidir.
- **Touchpad Gecikme Önleme:** I2C kontrolcüsünün boşta gereksiz yere uykuya dalmasını engelleyerek ilk dokunuştaki takılmayı tamamen yok eder.
- **Donanım Güç Profilleri:** PCIe ASPM (`powersupersave`), NVMe runtime PM (`auto`), Intel EPP ve ses kartı güç tasarrufunu otomatik yönetir.
- **Sıfır Arka Plan Döngüsü:** Pili izlemek için sürekli CPU yoran arka plan döngüleri çalıştırmaz; tüm işlemler `udev`, `sysfs` ve DBus olaylarıyla tetiklenir.
- **GTK4 / Libadwaita Arayüzü & CLI:** Hızlı ön ayarlar sunan masaüstü uygulaması (`ff-power-manager`) ve terminal kontrol aracı (`ffctl`).

---

## Gerçek Kullanım Süreleri (87 Wh Batarya)

Fedora 44 (Linux 7.x, GNOME Wayland, ~%30–40 OLED parlaklığı) altında ölçülen değerler:

| Senaryo | Ortalama Tüketim | Tahmini Çalışma Süresi |
| :--- | :---: | :---: |
| **Hafif Kullanım** (Web, VS Code, terminal, doküman - 60Hz) | ~8.0 – 9.0 W | **~9.5 – 10.5 Saat** |
| **Karma / Ağır Yük** (Derleme, çoklu görev, müzik) | ~11.0 – 12.5 W | **~7.0 – 8.5 Saat** |
| **Şarjda (AC)** | — | 120 Hz + VRR, Tam Performans |

---

## Bağımlılıklar

Fedora üzerinde:

```bash
sudo dnf install -y python3-gobject gtk4 libadwaita iw power-profiles-daemon polkit intel-media-driver libva-utils
```

---

## Kurulum

Repoyu klonlayıp kurulum betiğini çalıştırın:

```bash
git clone https://github.com/lwrlock/ff-power-manager.git
cd ff-power-manager
chmod +x install.sh
sudo ./install.sh
```

Uygulama menüsünden **FF Power Manager** simgesine tıklayarak veya terminalden başlatabilirsiniz:

```bash
ff-power-manager
```

Terminal üzerinden durum kontrolü:

```bash
ffctl status
```

---

## Tarayıcı Donanım Video Hızlandırma

YouTube ve video izlerken pil tüketimini düşürmek için Brave veya Chrome üzerinde `brave://flags` (veya `chrome://flags`) adresine gidin. **Hardware-accelerated video decode** ayarını **Enabled** yapıp tarayıcıyı yeniden başlatın.

---

## Katkıda Bulunma

Farklı bir Lenovo modelinde denediyseniz veya katkı sağlamak isterseniz [CONTRIBUTING.tr.md](CONTRIBUTING.tr.md) kılavuzuna bakabilirsiniz.

---

## Lisans

MIT Lisansı. Telif Hakkı (c) 2026 lwrlock. Ayrıntılar için [LICENSE](LICENSE) dosyasına bakabilirsiniz.
