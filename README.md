# Telegram avtomatik post tizimi

Berilgan rubrikada internetdan mavzu topib, post yozib, rasm va ovoz
generatsiya qilib, sifat nazoratidan o'tkazib, belgilangan vaqtda kanalga
chiqaradigan 6 agentli tizim.

```
Rubrika: "Xitoy savdosi maslahatlari"
   │
   ├─ 1. IZLOVCHI      Gemini + Google qidiruv → mavzu nomzodlari
   │                   arxiv bilan solishtiradi, takrorini tashlaydi
   ├─ 2. YOZUVCHI      sizning stilingizda post yozadi
   │        ↑          (style/examples.md dan o'rganadi)
   │        │
   ├─ 5. NAZORATCHI ───┘  rad etsa 2-agentga qaytaradi (2 martagacha)
   │
   ├─ 3. RASSOM        Nano Banana → post rasmi
   ├─ 4. OVOZ          Azure Speech uz-UZ → audio
   │                   rasm + audio → MP4
   │
   └─ 6. CHIQARUVCHI   adminga tasdiqqa → tugma bosiladi → kanalga
```

---

## 1. Nima kerak

| Nima | Qayerdan | Majburiymi |
|---|---|---|
| Telegram bot token | [@BotFather](https://t.me/BotFather) → `/newbot` | ha |
| Kanal manzili | `@kanal_nomi` yoki `-100...` | ha |
| Gemini API key | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | ha |
| Sizning Telegram ID | [@userinfobot](https://t.me/userinfobot) ga yozing | tasdiq uchun |
| Azure Speech key + region | Azure portal → Speech service (F0 bepul) | ovoz uchun |

**Botni kanalga admin qiling** — kanal → Administrators → Add Admin → botingiz →
"Post Messages" yoqilgan bo'lsin. Busiz hech narsa chiqmaydi.

---

## 2. Qayerda ishlatish — uchta yo'l

Tizim ishlashi uchun uchta narsa kerak: **jadval** (vaqtida ishga tushirish),
**kalitlarni saqlash joyi** va **arxiv saqlanadigan joy**. Quyidagi uch
variantning har biri bularni beradi — o'zingizga qulayini tanlang.

| | GitHub Actions | Server (VPS) | O'z kompyuteringiz |
|---|---|---|---|
| Narxi | bepul | ~$4–5 / oy | bepul |
| O'rnatish | oson | o'rtacha | oson |
| Kompyuter yoqiq turishi | shart emas | shart emas | **shart** |
| Server bilimi | kerak emas | ozgina | kerak emas |
| Qaysi bo'lim | **2A** | **2B** | **2C** |

Ikkinchi va uchinchi variantda GitHub umuman kerak emas — kod ichida
o'zining jadvali bor (`src/scheduler.py`), cron ham talab qilinmaydi.

---

## 2A. GitHub Actions

**1)** Yangi **private** repo oching va bu papkani ichiga yuklang.

**2)** `config.yaml` tekshiring — kanal va rubrika oldindan to'ldirilgan:

```yaml
channel:
  id: "@immensus_cargoo"        # boshqa kanal bo'lsa — shu yerni o'zgartiring
```

**3)** `style/examples.md` — ichida **boshlang'ich namunalar bor**, tizim
darhol ishlay boshlaydi. Lekin o'z postlaringizni sinab ko'rgach, eng yaxshi
ishlaganlarini shu yerga ko'chiring va boshlang'ich namunalarni o'chiring.

> Bu fayl postlarning ohangini belgilaydi. Post sizning uslubingizda
> chiqmayotgan bo'lsa — deyarli har doim aynan shu faylni yangilash kerak.

**4)** Repo → **Settings → Secrets and variables → Actions → New repository secret**.
Quyidagilarni bittalab qo'shing:

```
TELEGRAM_BOT_TOKEN
TELEGRAM_ADMIN_CHAT_ID
GEMINI_API_KEY
AZURE_SPEECH_KEY
AZURE_SPEECH_REGION
```

**5)** Repo → **Settings → Actions → General → Workflow permissions** →
**Read and write permissions** ni yoqing. Busiz tizim arxivni saqlay olmaydi.

**6)** Repo → **Actions** → "Post tayyorlash" → **Run workflow** bilan sinab ko'ring.

> ⚠️ **Vaqt aniqligi haqida.** GitHub cron'ining eng kichik oralig'i 5 daqiqa
> va u ko'pincha yana bir necha daqiqa kechikadi. 10 daqiqalik ko'rish oynasi
> uchun bu aniqlik chegarada — post 5–10 daqiqa kech chiqishi mumkin.
>
> Aniq vaqt muhim bo'lsa, ikkita yechim bor: `config.yaml` da
> `preview_minutes` ni **30** ga oshiring, yoki **2B / 2C** yo'lini tanlang —
> u yerdagi ichki jadval har 60 soniyada tekshiradi.

---

## 2B. Server (VPS) — GitHub'siz

Har qanday arzon Linux server bo'ladi: Hetzner, DigitalOcean, Contabo, Vultr —
eng kichik tarif yetadi. Bu yerda GitHub Actions o'rniga kod **o'zi**
vaqtni kuzatib turadi.

### Docker bilan (eng oson)

```bash
# serverda
git clone <yoki papkani yuklang> tg-autopost
cd tg-autopost

cp .env.example .env
nano .env                    # kalitlarni yozing
nano config.yaml             # channel.id ni yozing
nano style/examples.md       # namuna postlaringizni qo'ying

docker compose up -d --build
docker compose logs -f       # jonli log
```

Tamom. Konteyner qayta ishga tushsa ham, server o'chib yonsa ham
o'zi tiklanadi (`restart: unless-stopped`). Arxiv va navbat `data/`
papkasida — konteynerdan tashqarida saqlanadi.

### Docker'siz (systemd bilan)

```bash
cd ~/tg-autopost
sudo apt update && sudo apt install -y python3-venv ffmpeg
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env && nano .env

# tekshiring
.venv/bin/python -m src.main check

# doimiy xizmat sifatida yoqing
sudo cp tg-autopost.service /etc/systemd/system/
sudo nano /etc/systemd/system/tg-autopost.service   # User va yo'llarni moslang
sudo systemctl daemon-reload
sudo systemctl enable --now tg-autopost
sudo journalctl -u tg-autopost -f
```

---

## 2C. O'z kompyuteringizda — GitHub'siz

Server olishni istamasangiz. Yagona shart: **post chiqadigan vaqtda
kompyuter yoqiq va internetga ulangan bo'lsin.**

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip

cp .env.example .env        # kalitlarni yozing
# config.yaml va style/examples.md ni to'ldiring

.venv/bin/python -m src.main check
.venv/bin/python -m src.scheduler              # shu oynani ochiq qoldiring
```

**Windows'da** `run.bat` faylini ikki marta bosing — o'sha ishni qiladi.
Kompyuter yonganda o'zi ishga tushishi uchun: Task Scheduler → Create Task →
Trigger "At log on" → Action: `run.bat`.

**macOS'da** `.venv/bin/python -m src.scheduler` ni Terminal'da qoldiring,
yoki `launchd` ga qo'ying.

ffmpeg alohida o'rnatiladi: Windows — [ffmpeg.org](https://ffmpeg.org/download.html),
macOS — `brew install ffmpeg`.

### Vaqt masalasi

Siz Xitoydasiz, kanal O'zbekiston vaqtida ishlaydi (farq 3 soat).
Buni siz hisoblamaysiz — `config.yaml` dagi `timezone` va `publish_times`
kanal vaqtida yoziladi, tizim o'zi to'g'ri vaqtga aylantiradi.
Kompyuteringizning vaqt zonasi qanday bo'lishidan qat'i nazar ishlaydi.

---

## 3. Qanday ishlaydi

Sukut bo'yicha rejim — **opt_out**: post o'zi chiqadi, siz faqat
to'xtatishingiz mumkin. Hech narsa qilmasangiz kanal har kuni yangilanadi.

```
08:45   tizim postni tayyorlaydi (mavzu → matn → rasm → ovoz → video)
08:47   post sizga Telegramda keladi:

        🎬 [video]
        post matni
        [ 🔄 Qayta ishlash ]  [ ❌ Bekor qilish ]

        ⏳ 09:00 da o'zi chiqadi (taxminan 13 daqiqadan keyin).
           Hech narsa bosmasangiz — chiqaveradi.

09:00   HECH NARSA BOSMADINGIZ  →  post kanalga chiqadi ✅
```

**"🔄 Qayta ishlash" bossangiz** — post 09:00 da chiqmaydi. Tizim uni
qaytadan yozadi, yangi rasm va ovoz tayyorlaydi va sizga qayta yuboradi.
Yangi variant **hozirdan 10 daqiqadan keyin** chiqadi:

```
08:52   🔄 bosildi           →  09:00 dagi chiqish bekor qilinadi
08:54   yangi variant keladi →  ⏳ 09:04 da chiqadi
09:04   post kanalga chiqadi ✅   (asl vaqt o'tib ketgan bo'lsa ham)
```

Ya'ni **qaytarilgan post baribir chiqadi** — faqat kechroq. Kanal
bo'sh qolmaydi.

**Ikkinchi marta qayta ishlash** bosilsa, tizim mavzuni ham almashtiradi —
demak muammo matnda emas, mavzuning o'zida. Chegara `max_rewrites` (3) ga
yetganda oxirgi variant baribir chiqariladi va sizga bu haqda yoziladi.

**"❌ Bekor qilish"** — post umuman chiqmaydi. Butunlay to'xtatish uchun.

Media Telegram'ga **bir marta** yuklanadi: sizga ko'rsatilganda. Kanalga
chiqarishda `file_id` ishlatiladi — qayta yuklanmaydi va repoga hech qanday
video tushmaydi.

### Boshqa rejimlar

```yaml
approval:
  mode: "opt_in"    # post faqat "✅ Chiqarish" bosilganda chiqadi
  mode: "off"       # ko'rsatilmaydi, to'g'ridan-to'g'ri chiqadi
```

`preview_minutes` — necha daqiqa oldin ko'rsatilishi. Uni oshirsangiz
ko'proq vaqtingiz bo'ladi, lekin post ham shuncha oldin tayyorlanadi.

---

## 4. Lokal sinov

```bash
pip install -r requirements.txt
cp .env.example .env          # kalitlarni to'ldiring

python -m src.main check      # ulanishlarni tekshiradi
python -m src.main generate   # post tayyorlaydi
python -m src.main status     # navbatni ko'rsatadi
python -m src.main tick       # tugmalarni o'qiydi va chiqaradi
```

Kalitlarsiz oqimni ko'rish:

```bash
MOCK=1 python -m src.main generate
```

`check` buyrug'i har bir bo'g'inni alohida tekshiradi — bot tokeni, kanalga
ulanish, botning admin ekani, Gemini matn, Gemini rasm, Azure ovoz, ffmpeg va
stil namunalari. Muammo bo'lsa aynan qaysi joyda ekanini ko'rsatadi.

---

## 5. Sozlash

Hammasi `config.yaml` ichida:

| Bo'lim | Nima |
|---|---|
| `rubrics` | Rubrikalar ro'yxati. Bir nechta bo'lsa navbatma-navbat ishlatiladi |
| `rubrics[].allowed_domains` | 1-agent faqat shu saytlardan izlaydi. Bo'sh = cheklovsiz |
| `post.min_chars` / `max_chars` | Post uzunligi |
| `post.emoji_level` | `none` / `low` / `medium` / `high` |
| `post.max_chinese_ratio` | Postdagi iyerogliflarning eng ko'p ulushi (0.15 = 15%) |
| `post.max_chinese_chars` | Iyerogliflar soni chegarasi (faqat ulush ham yuqori bo'lsa ishlaydi) |
| `image.model` | `gemini-2.5-flash-image`, `gemini-3.1-flash-image`, `gemini-3-pro-image` |
| `image.style` | Rasm uslubi — brend ranglaringizni shu yerga yozing |
| `audio.voice` | `uz-UZ-SardorNeural` (erkak) yoki `uz-UZ-MadinaNeural` (ayol) |
| `video.enabled` | `false` qilsangiz rasm + alohida audio yuboriladi |
| `llm.max_rewrites` | Nazoratchi rad etsa necha marta qayta yozilsin |
| `llm.qc_min_score` | O'tish uchun kerakli ball (1–10). Doim rad etsa — 6 ga tushiring |
| `llm.qc_last_chance` | Oxirgi urinishda shartli o'tish chegarasi. `null` = qat'iy rejim |
| `schedule.publish_times` | Chiqish vaqtlari, kanal vaqt zonasida |
| `approval.mode` | `opt_out` (o'zi chiqadi) / `opt_in` (tasdiq shart) / `off` |
| `approval.preview_minutes` | Chiqishdan necha daqiqa oldin sizga ko'rsatilsin |
| `approval.rewrite_review_minutes` | Qayta ishlangan post necha daqiqadan keyin chiqsin |
| `approval.max_rewrites` | Bir post uchun qayta ishlash chegarasi |

Kuniga 2 ta post kerak bo'lsa: `publish_times: ["09:00", "20:00"]` va
`generate.yml` dagi cron ni ikki marta ishga tushadigan qilib qo'ying.

---

## 6. Fayllar

```
config.yaml              barcha sozlamalar (kalitlar bu yerda EMAS)
style/examples.md        sizning namuna postlaringiz ← eng muhim fayl
data/archive.json        yozilgan mavzular — takrorlanmaslik uchun
data/pending.json        navbat va tasdiq holatlari
src/agents/a1..a6        oltita agent
src/gemini.py            Gemini REST klienti (API o'zgarishlariga chidamli)
src/azure_tts.py         Azure Speech + matnni ovozga tayyorlash
src/video.py             rasm + audio → MP4 (ffmpeg)
src/telegram.py          Bot API
src/store.py             arxiv, navbat, offset
src/main.py              orkestrator
src/scheduler.py         ichki jadval — GitHub'siz ishlatish uchun

.github/workflows/       ← faqat 2A (GitHub) yo'li uchun
Dockerfile               ← faqat 2B (server) yo'li uchun
docker-compose.yml       ←
tg-autopost.service      ←
run.bat                  ← faqat 2C (Windows) yo'li uchun
```

Tanlagan yo'lingizga tegishli bo'lmagan fayllarni o'chirib tashlasangiz ham
bo'ladi — bir-biriga xalaqit bermaydi.

---

## 7. Muammolar

**"Bot kanalda admin emas"** — kanal sozlamalarida botga "Post Messages"
huquqini bering.

**"Barcha topilgan mavzular arxivda bor"** — rubrika juda tor.
`rubrics[].brief` ni kengaytiring yoki `allowed_domains` ni oching.

**Gemini rasm xatosi** — `image.model` ni almashtirib ko'ring. Kod uchta
model nomini ham qo'llaydi, `check` buyrug'i qaysi biri ishlashini aytadi.

**Ovoz g'alati o'qiyapti** — `uz-UZ-MadinaNeural` ni sinab ko'ring, yoki
`audio.rate: "-5%"` bilan sekinlashtiring.

**Post sizning stilingizda emas** — `style/examples.md` ga ko'proq va
sifatliroq namuna qo'shing. Bu deyarli har doim shu faylning muammosi.

**"404" yoki "model not found"** — model nomi eskirgan. `config.yaml` da
`llm.model` va `llm.qc_model` ni `gemini-3.6-flash` yoki `gemini-3.7-flash`
qilib qo'ying. Rasm uchun `image.model` ni ham tekshiring.

**Post xitoycha bo'lib ketdi** — bu tekshiruv avtomatik. Nom va atamalar
(义乌, 阿里巴巴, 1688, 拼多多) bemalol o'tadi — o'nlab bo'lsa ham. Lekin
matnning **15% dan ortig'i** iyeroglif bo'lsa, post rad etiladi va o'zbek
tilida qayta yoziladi. Chegarani `post.max_chinese_ratio` bilan o'zgartirasiz,
`null` qilsangiz tekshiruv butunlay o'chadi.

**5-agent postni doim rad etyapti** — uchta sabab bo'lishi mumkin:

1. `style/examples.md` bo'sh yoki namunalar zaif. Nazoratchi postni
   namunalarga solishtiradi — solishtiradigan narsa bo'lmasa qattiq baho beradi.
2. Chegara yuqori. `llm.qc_min_score` ni 7 dan 6 ga tushiring.
3. Mavzu tor — 1-agent yaxshi material topa olmagan, 2-agent esa bo'sh
   materialdan post yozgan. `rubrics[].brief` ni kengaytiring.

Oxirgi urinishda post `llm.qc_last_chance` balidan yuqori bo'lsa,
u **shartli** o'tadi va sizga "⚠️ past ball" belgisi bilan boradi —
o'zingiz o'qib qaror qilasiz. Bu chegarani `null` qilsangiz eski
qat'iy rejim qaytadi. Mexanik xatolar (kod bloki, qisqa matn,
hashtagsiz) esa hech qachon kechirilmaydi.

Bir martalik holat uchun: Actions → Run workflow → `force` ni yoqing,
yoki lokalda `python -m src.main generate --force`.

**"Qayta ishlash" bosdim, lekin yangi variant kelmadi** — tizim tugmani
keyingi tekshiruvda ko'radi: ichki jadvalda 60 soniya, GitHub'da 5 daqiqa
(kechikish bilan ko'proq). Undan keyin qayta yozish 1–3 daqiqa oladi.
Umuman kelmasa — log'ga qarang: sifat nazoratidan o'tmagan bo'lishi mumkin,
bunda sizga "qayta yozilmadi" degan xabar keladi.

**Post kech chiqdi** — GitHub Actions cron'i kechikadi. `preview_minutes` ni
oshiring yoki ichki jadvalga (2B / 2C) o'ting.

**Postni umuman to'xtatish kerak** — "❌ Bekor qilish" tugmasi. Yoki
`data/pending.json` da o'sha yozuvning `status` ini `cancelled` qiling.

---

## Xarajat

Gemini Flash matn + rasm va Azure F0 bepul tarifi bilan kuniga 1–2 post
amalda deyarli bepul chiqadi. GitHub Actions public repo uchun bepul,
private repo uchun oyiga 2000 daqiqa bepul beriladi — bu tizim kuniga
~3 daqiqa ishlatadi.

---

## 8. Boshqa variantlar

Yuqoridagi uchtasi eng oddiy yo'llar. Yana bir nechta imkoniyat bor:

**Railway / Render / Fly.io** — server olishni istamasangiz, lekin
kompyuteringiz doim yoqiq bo'lmasa. `Dockerfile` tayyor: repoyni ulaysiz,
kalitlarni ularning Variables bo'limiga qo'yasiz, ishga tushadi.
Bepul tariflar cheklangan, lekin bu tizim juda kam resurs ishlatadi.

**Oddiy cron** (ichki jadvalsiz) — server sizda bor va cron'ni afzal ko'rsangiz:

```cron
0  20 * * *  cd /home/ubuntu/tg-autopost && .venv/bin/python -m src.main generate >> logs/gen.log 2>&1
*/10 * * * *  cd /home/ubuntu/tg-autopost && .venv/bin/python -m src.main publish  >> logs/pub.log 2>&1
```

Bunda `src/scheduler.py` ishlatilmaydi — cron o'zi vaqtni boshqaradi.
