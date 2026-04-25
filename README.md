# Referral Bot — To'liq versiya

## O'rnatish

### 1. Python va pip
```bash
pkg install python        # Termux
sudo apt install python3 python3-pip  # VPS (Ubuntu/Debian)
```

### 2. Kutubxonalar
```bash
pip install -r requirements.txt
```

### 3. config.py ni sozlash
```python
BOT_TOKEN = "BotFather dan olingan token"
ADMIN_IDS = {12345678}           # Admin Telegram ID
REQUIRED_CHANNELS = ["@kanal1"]  # Majburiy kanallar
```

### 4. Ishga tushirish

**Termux (oddiy):**
```bash
python bot.py
```

**Termux (orqa fonda — terminal yopilsa ham ishlaydi):**
```bash
nohup python bot.py > bot.log 2>&1 &
```

**VPS (systemd — server o'chsa ham qayta ishga tushadi):**

`/etc/systemd/system/refbot.service` faylini yarating:
```ini
[Unit]
Description=Referral Telegram Bot
After=network.target

[Service]
WorkingDirectory=/root/refbot
ExecStart=/usr/bin/python3 /root/refbot/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable refbot
sudo systemctl start refbot
sudo systemctl status refbot   # holat
sudo journalctl -u refbot -f   # loglar
```

---

## Funksiyalar

| Funksiya | Tavsif |
|----------|--------|
| 🔗 Referral link | Shaxsiy link olish va ulashish |
| 📊 Statistika | Nechta odam taklif qilgani |
| 🏆 Top 10 | Eng ko'p referral qilganlar |
| ✅ A'zolikni tekshirish | Kanal a'zoligini tasdiqlash |
| 📥 Statistika (.txt) | [Admin] Barcha userlar statistikasi fayl sifatida |
| 🛑 Stop konkurs | [Admin] Konkursni to'xtatish |
| ▶️ Konkursni boshlash | [Admin] Konkursni qayta boshlash |
| /AllUserMessage | [Admin] Barcha userlarga xabar yuborish |

---

## Backup tizimi

- Har yangi referral qo'shilganda yoki qayta faollashganda **avtomatik backup** qilinadi
- Backup fayllari `backups/` papkasiga saqlanadi (`backup_YYYYMMDD_HHMMSS.db`)
- Bir vaqtda oxirgi **30 ta backup** saqlanadi, eskisi o'chiriladi
- Har backup bo'lganda **adminlarga Telegram orqali** fayl yuboriladi
- Server yonsa ham backup fayllar xavfsiz saqlanadi

## Referral -1 / qayta tiklanish logikasi

- Har 30 daqiqada bot kanallarni tekshiradi
- Kimdir kanaldan chiqib ketsa → referral **vaqtincha o'chiriladi** (bazadan o'chirmaydi)
- Referral beruvchiga "⚠️ Referral vaqtincha bekor qilindi" xabari ketadi
- Chiqib ketgan odam qaytib kirsa → referral **avtomatik tiklanadi** ✅
- Referral beruvchiga "🔄 Foydalanuvchi qaytib keldi" xabari ketadi

## Flood himoya

- `/AllUserMessage` har 25 xabardan keyin 1 soniya kutadi
- Bot bloklagan userlar jimgina o'tkazib yuboriladi (hech qanday log yo'q)
