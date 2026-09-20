# Fedora Gelistirme Ortami

Bu dosya, FF Power Manager geliştirmek için temiz Fedora GNOME kurulumundan sonra gereken ortamı hazırlar.

## Ne kurulur?

- FPM icin Python, PyGObject, GTK 4, Libadwaita ve test araclari
- Git, derleme araclari, ripgrep ve ShellCheck
- Microsoft'un resmi Fedora deposundan Visual Studio Code
- Flathub'dan Spotify ve GNOME Extension Manager
- Fedora deposundan GNOME Tweaks, Extensions ve `adw-gtk3-theme`

`adw-gtk3-theme`, eski GTK3 uygulamalarini GNOME'un yerlesik Adwaita gorunumuyle uyumlu hale getirir. GNOME/Libadwaita uygulamalarinin temasi zorla degistirilmez; bu, surum guncellemelerinde daha stabil kalir.

## Kurulum

```bash
chmod +x scripts/setup-fedora-workstation.sh
./scripts/setup-fedora-workstation.sh
```

Sonra GNOME'dan cikis yapip tekrar gir. `gnome-tweaks` ile gorunumu, Extension Manager ile de GNOME surumunle uyumlu eklentileri yonetebilirsin.

## FPM'i calistirma

Once test:

```bash
make test
```

Sonra uygulamayi sistemine kurmak istersen:

```bash
./install.sh
```

`install.sh` sistem servisleri ve udev kurallari ekledigi icin bunu ancak proje klasorunun dogru oldugundan emin olduktan sonra calistir.

## Kaynaklar

- Visual Studio Code, Microsoft'un imzali RPM deposundan gelir.
- Spotify ve Extension Manager, Flathub uzerinden kurulur.
- GNOME temasi ve Tweaks paketleri Fedora'nin kendi deposundandir.
