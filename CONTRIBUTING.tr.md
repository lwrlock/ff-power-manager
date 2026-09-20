# FF Power Manager'a Katkıda Bulunma

[ [English](CONTRIBUTING.md) | Türkçe ]

Projeye göz attığınız için teşekkürler! İster bir hata bildirin, ister yeni bir özellik önerin, ister kendi dizüstü bilgisayarınızdaki test sonuçlarını paylaşın; her türlü katkı çok değerlidir.

---

## Farklı Cihazlarda ve Donanımlarda Test Etme

Bu araç **Lenovo IdeaPad Pro 5 14IAH10** (Intel Core Ultra 9 285H, Samsung 2.8K OLED, ST VL53L1 ToF sensör) üzerinde geliştirilmiş ve optimize edilmiştir.

Lenovo farklı modellerde ufak BIOS, güç tablosu ve sensör HID descriptor değişiklikleri yapabiliyor. Eğer aracı farklı bir Lenovo modelinde (veya farklı bir Linux dağıtımında) deniyorsanız, donanım geri bildirimleriniz projeyi geliştirmek için son derece faydalıdır.

Uyumluluk bildirimlerinde şu çıktıları eklemeniz yeterlidir:
```bash
# Model ve BIOS sürümü
cat /sys/class/dmi/id/product_name
cat /sys/class/dmi/id/product_version

# Çekirdek ve dağıtım
uname -r
cat /etc/os-release | grep PRETTY_NAME

# Güç durumu
ffctl status
```

Cihazınızda ToF varlık sensörü varsa, sensör servisinin durumunu kontrol edebilirsiniz:
```bash
journalctl -u ff-presence-sensor.service -n 50 --no-pager
```

---

## Geliştirme İlkeleri

Kod katkısı yaparken lütfen şu temel prensipleri göz önünde bulundurun:

1. **Gereksiz arka plan döngüleri eklemeyin:** Bir batarya yönetim aracı güç tasarrufu sağlamak için geliştirilir; kendisi sürekli CPU tüketerek pili bitirmemelidir. Tüm işlemler donanım kesintilerine (`select(2)`), dosya izleyicilerine (`GFileMonitor`) veya çekirdek olaylarına (`udev`) bağlı olmalıdır.
2. **%100 çevrimdışı ve gizli:** Telemetri, dış ağ çağrısı, analitik veya veri toplama kesinlikle kabul edilmez. Her şey tamamen cihazın kendi içinde çalışır.
3. **Güvenli dosya işlemleri:** Ayar güncellemeleri atomik (`.tmp` -> `replace`) yapılmalı ve veri tipleri doğrulanmalıdır; böylece ani kapanmalarda dosyalar bozulmaz.
4. **Temiz yetki ayrımı:** Masaüstü arayüzü ve oturum servisleri standart kullanıcı yetkileriyle çalışır. Root yetkisi gerektiren işlemler Polkit helper (`ff-power-helper`) üzerinden beyaz listedeki eylemlerle sınırlandırılmıştır.

---

## Testleri Çalıştırma

Bir Pull Request göndermeden önce birim testlerin ve sözdizimi kontrollerinin sorunsuz geçtiğinden emin olun:

```bash
# Birim testleri çalıştırma
PYTHONPATH=src python3 -m unittest discover -s tests -v

# Python sözdizimi kontrolü
python3 -m py_compile src/fpm/*.py
```

---

## Pull Request Gönderme

1. Projeyi GitHub üzerinde forklayın.
2. Değişikliğiniz için temiz bir dal (branch) açın:
   ```bash
   git checkout -b feature/yenilik
   ```
3. Anlaşılır ve açıklayıcı commit mesajları kullanın.
4. Dalınızı forkladığınız repoya pushlayıp bir Pull Request açın.

Farklı bir yaklaşım veya büyük bir değişiklik planlıyorsanız, önce bir Issue açarak fikir alışverişinde bulunabilirsiniz!
