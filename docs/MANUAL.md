# คู่มือใช้งานและแก้ไข autovideo

คู่มือนี้เขียนให้ใช้ได้โดยไม่ต้องมี Claude Code: ระบบทำงานอะไรเอง อะไรต้องกด จะแก้ค่าตรงไหน และเมื่อพังต้องทำอะไร
(อัปเดต 2026-11-16)

---

## 1. ภาพรวม: ระบบทำอะไรเองบ้าง

```
                      ┌──────────────── Windows ────────────────┐
  ล็อกอิน Windows ──▶ │ Task Scheduler "AutoVideo-KeepWSL"      │
                      │ เปิด WSL ค้างไว้ ถูกปิดเมื่อไรเปิดใหม่ใน 15 วิ │
                      └───────────────────┬─────────────────────┘
                                          ▼
   ┌──────────────────────────── WSL (Ubuntu) ────────────────────────────┐
   │ autovideo-bot.service  (เปิดเองทุกครั้งที่ WSL เริ่ม, ล่มแล้วเปิดใหม่เอง) │
   │   ├─ บอท Telegram: รับคำสั่ง/ปุ่ม, ส่งบท ส่งคลิป ส่งแจ้งเตือน            │
   │   └─ ตัวทำงาน (worker): หยิบงานจากคิวทำทีละขั้น                       │
   │                                                                       │
   │ autovideo-daily.timer  ทุกวัน 08:00 → ใส่นิทานตอนถัดไปลงคิว            │
   └───────────────────────────────────────────────────────────────────────┘
```

**งาน 2 ประเภทในคิวเดียวกัน**

| ประเภท | สร้างด้วย | ขั้นตอน | เวลา |
|---|---|---|---|
| คลิปความรู้ (short) | `/new [หัวข้อ]` | Gemini เขียนบท → **คุณอนุมัติบท** → เสียง → ภาพ/คลิป Pixabay → ตัดต่อ → QC → **คุณอนุมัติโพสต์** → YouTube | ~3–5 นาที |
| นิทานเป็นตอน (story) | `/story` หรืออัตโนมัติ 08:00 | ใช้บทในไฟล์เรื่อง (ถ้าไม่มี Gemini เขียนจากโครงเรื่อง) → **คุณอนุมัติบท** → เสียง → วาดภาพ AI 3 แบบ/ช็อต → AI เลือกภาพที่ตรงสุด (CLIP) → ทำให้ขยับ (LTX 6 ช็อต + 2.5 มิติที่เหลือ) → ตัดต่อ → QC → **คุณอนุมัติโพสต์** → YouTube | ~1.5–2.5 ชม. (การ์ดจอ) |

**ไม่มีอะไรถูกโพสต์ ถ้าคุณไม่กดปุ่ม "โพสต์" ใน Telegram เอง** (และไม่มีโหมดข้ามขั้นนี้)

---

## 2. ใช้งานประจำวัน (Telegram)

บอท: **@Short_Video_Pk_bot** — ตอบเฉพาะบัญชีเจ้าของ (chat id ใน `.env`) คนอื่นพิมพ์มาบอทเงียบ

| คำสั่ง | ทำอะไร |
|---|---|
| `/help` | วิธีใช้ทุกคำสั่งและทุกปุ่ม |
| `/list` | งานทั้งหมดแยกกลุ่ม: รอคุณ / กำลังทำ / ล้มเหลว / โพสต์แล้ว / ยกเลิก + นิทานทุกตอน |
| `/status` | 10 งานล่าสุดแบบสั้น |
| `/new [หัวข้อ]` | คลิปความรู้ 1 งาน (ไม่ใส่หัวข้อ = Gemini เลือก) |
| `/story [ตอน]` | นิทานตอนถัดไป (หรือระบุตอน) ของเรื่องใน `story.series` |
| `/progress` | งานนิทานล่าสุดวาดถึงไหน + เวลาที่คาดว่าเสร็จ |
| `/eta` | คาดว่าทุกงานในคิวจะเสร็จกี่โมง (คิดจากความเร็วจริงล่าสุดของเครื่อง ร้อนแล้วช้าก็คิดให้) |
| `/report on` / `/report off` | เปิด/ปิดรายงานทุก 10 นาทีระหว่างทำนิทาน (จำค่าไว้ใน `data/settings.json`) · **ปิดแล้วยังแจ้งเสมอ:** บทพร้อม, คลิปเสร็จ, ไม่ผ่าน QC, ล้มเหลว, โพสต์แล้ว, ระบบเปิด/ปิด |
| `/cancel <เลข>` | ยกเลิกงาน |
| `/retry <เลข>` | ลองใหม่งานที่ล้มเหลว (งานไม่ผ่าน QC = ทำเสียงและภาพใหม่) |

**แจ้งเตือนอัตโนมัติ:** 🟢 ระบบเปิด (บอกว่าปิดไปตั้งแต่เมื่อไร ปกติหรือดับกะทันหัน และงานที่จะทำต่อ) · 🔴 ระบบปิด (ตอนปิดตามปกติ) · ⏱ ความคืบหน้าทุก 10 นาทีระหว่างทำนิทาน

**ปุ่ม**
- ตอนรอยืนยันบท: **อนุมัติ** / **เขียนใหม่** (สูงสุด 3 ครั้ง) / **แก้ไข** (กดแล้วพิมพ์สิ่งที่อยากแก้ส่งไป) / **ยกเลิก**
- ตอนรอยืนยันโพสต์ (ส่งคลิปมาให้ดูก่อน): **โพสต์** / **ทำใหม่** (บทเดิม ภาพใหม่ทั้งหมด) / **ยกเลิก**
- ตอน **ไม่ผ่าน QC**: ส่งคลิปมาให้ดูพร้อมบอกข้อที่ไม่ผ่าน มีปุ่มเหมือนกัน — ถ้าดูแล้วไม่เป็นปัญหา (เช่นยาวเกินเพดานไม่กี่วินาที) กด **โพสต์** ได้เลย
- กดได้ครั้งเดียว กดซ้ำบอทจะบอกว่า "ปุ่มนี้ใช้ไปแล้ว"

**วันปกติของนิทาน:** 08:00 ระบบใส่ตอนถัดไปลงคิว → บอทส่งบทมา → คุณกดอนุมัติ → ~2 ชม. ต่อมาบอทส่งคลิป → คุณกดโพสต์
**จำกัด** `limits.max_jobs_per_day` งานต่อวัน (ตอนนี้ 2) นับรวมทุกประเภท

**โพสต์แล้วคลิปไปไหน:** ขึ้นช่องเป็น **ส่วนตัว (private)** ตาม `youtube.privacy` บอทส่งลิงก์ Studio มาให้ ไปกดเผยแพร่เองที่ https://studio.youtube.com → เนื้อหา → Shorts
> ⚠️ โปรเจกต์ Google Cloud ที่ยังไม่ผ่าน "YouTube API Audit" — คลิปที่อัปผ่าน API อาจถูกล็อกเป็นส่วนตัว เปลี่ยนเป็นสาธารณะไม่ได้ ทางแก้: ยื่น audit (ฟรี ใช้เวลา) หรือดาวน์โหลดไฟล์จาก `data/jobs/<เลข>/final.mp4` แล้วอัปเองผ่านแอป YouTube

---

## 3. สิ่งที่รันอยู่ และคำสั่งดูแล (พิมพ์ใน terminal ของ WSL)

```bash
cd ~/projects/short_video_bot

systemctl --user status autovideo-bot          # บอท+ตัวทำงาน: active (running) = ปกติ
systemctl --user restart autovideo-bot         # รีสตาร์ท (หลังแก้ config.yaml / .env / โค้ด ต้องทำ)
systemctl --user stop autovideo-bot            # หยุดชั่วคราว
systemctl --user list-timers autovideo-daily.timer   # ดูว่า 08:00 รอบหน้าเมื่อไร

tail -f data/logs/autovideo.log                # log หลักของงานทุกขั้น
tail -f data/logs/bot.log                      # error ของบอท/ตัวทำงานเอง
uv run autovideo jobs                          # ดูงานจาก terminal
uv run autovideo doctor                        # ตรวจว่าตั้งค่าครบไหม
```

**ติดตั้ง service ใหม่** (ย้ายโฟลเดอร์ / เครื่องใหม่ / unit หาย): `scripts/install_services.sh`
**Windows ฝั่ง keepalive** (เครื่องใหม่ หรือเผลอลบ task): ใน PowerShell
`powershell -ExecutionPolicy Bypass -File \\wsl$\Ubuntu\home\aunny\projects\short_video_bot\scripts\install_windows_keepalive.ps1`
ลบ: `Stop-ScheduledTask AutoVideo-KeepWSL; Unregister-ScheduledTask AutoVideo-KeepWSL -Confirm:$false`

**รีสตาร์ท/ปิด WSL โดยตั้งใจ** (task จะเปิด WSL กลับเองใน 15 วิ ถ้าไม่หยุด task ก่อน) ใน PowerShell:
```powershell
Stop-ScheduledTask AutoVideo-KeepWSL      # หยุดตัวเปิดค้าง
wsl --shutdown                            # ปิด WSL (งานที่ทำอยู่จะทำต่อเองตอนเปิดใหม่)
Start-ScheduledTask AutoVideo-KeepWSL     # เปิดกลับ (หรือรอล็อกอินครั้งหน้า)
```
ตัวลูปอยู่ฝั่ง Windows ที่ `%LOCALAPPDATA%\autovideo\keepwsl.ps1`

---

## 4. แก้ปัญหา (อาการ → สาเหตุ → ทำอะไร)

| อาการ | สาเหตุที่เป็นไปได้ | ทำอะไร |
|---|---|---|
| บอทไม่ตอบเลย | WSL ไม่ได้เปิด / service หยุด | เปิด terminal Ubuntu สักครั้ง แล้ว `systemctl --user status autovideo-bot` ถ้าไม่ active: `systemctl --user restart autovideo-bot` ดู error ใน `data/logs/bot.log` |
| บอทไม่ตอบหลังรีสตาร์ท Windows | task keepalive ไม่ทำงาน | Task Scheduler → หา `AutoVideo-KeepWSL` → Run / หรือรันสคริปต์ keepalive ข้างบนใหม่ |
| คอมเข้าโหมด Sleep แล้วงานหยุด | Windows หลับ = ทุกอย่างหยุดชั่วคราว | ตอนทำนิทานตั้ง Windows ไม่ให้หลับตอนเสียบสาย: Settings → System → Power → Sleep (on AC) = Never · ตื่นแล้วงานทำต่อเอง |
| งานค้างสถานะเดิมนาน | งานนิทานใช้ 1.5–2.5 ชม. เป็นปกติ / ตัวทำงานค้าง | `/progress` ดูนิทาน, `tail data/logs/autovideo.log` ถ้าไม่ขยับ >30 นาที: `systemctl --user restart autovideo-bot` (งานทำต่อจากที่ค้าง ไม่เริ่มใหม่) |
| ขึ้น ❌ ล้มเหลว | ดูข้อความ error ในแจ้งเตือน | แก้ตามข้อความ แล้ว `/retry <เลข>` (ระบบลองเองให้ 3 ครั้งก่อนแจ้ง) |
| "การเชื่อม YouTube หมดอายุ" | แอปโหมด Testing หมดทุก 7 วัน | บนคอม: `uv run autovideo auth youtube` เปิดลิงก์ที่ขึ้น (ในคอมเครื่องนี้) เลือก Gmail ของช่อง → อนุญาต แล้ว `/retry <เลข>` · ถาวร: ทำหน้า privacy policy + homepage แล้ว Publish app ใน Google Auth Platform → Audience |
| อัปโหลด error 404 "notFound" | บัญชีที่อนุญาตไม่มีช่อง / ช่องเพิ่งสร้าง | รอสักพักแล้ว `/retry` ถ้ายังเป็น ทำ auth ใหม่และเลือกบัญชีที่มีช่อง |
| "โควตา AI หมด เลื่อนไปทำต่อ..." | Gemini ฟรีหมดโควตาวัน (429) | ไม่ต้องทำอะไร ระบบทำต่อเองหลังเที่ยงคืน |
| Gemini ตอบช้ามาก/ไม่ตอบ | รุ่นนั้นคนใช้เยอะ | เปลี่ยน `llm.model` (ทดสอบแล้ว: `gemini-3.6-flash`, `gemini-3.5-flash` เร็ว · 3.7/3.8 ช้า 3–5 นาที · 2.5 ปิดแล้ว) แล้ว restart บอท |
| edge-tts "Timeout" | เน็ตหลุด | ระบบลองใหม่เอง ถ้าล้มเหลวกด `/retry` · ถ้าเสียงหายทั้งระบบ ลองเปลี่ยน `tts.voice` (ดูรายชื่อ `uv run edge-tts --list-voices`) |
| นิทานวาดช้ามาก | การ์ดจอร้อน (เคยเจอ 91°C เหลือ 15% ความเร็ว) | ระบบพักเองเมื่อ >85°C · ช่วยได้: เสียบสายชาร์จ, ยกเครื่องให้ลมผ่าน, พัดลมรอง, โหมดพลังงานสูงสุด |
| "ltx ... ล้มเหลว" / คลิปนิ่งทั้งหมด | LTX ทำให้ขยับไม่สำเร็จ (หน่วยความจำ) | ไม่พัง: ระบบใช้ภาพ 2.5 มิติแทนอัตโนมัติ · ปิด AI ขยับถาวร: `story.ai_motion: false` |
| "sdxl/pick/parallax ล้มเหลว (exit 137)" | RAM เกินเพดาน 5 GB ของขั้นนั้น | ปิดโปรแกรมอื่นใน WSL แล้ว `/retry` · เพิ่ม RAM ให้ WSL ใน `C:\Users\aunny\.wslconfig` (`[wsl2]` `memory=10GB`) แล้ว `wsl --shutdown` |
| CUDA out of memory | การ์ดจอ 6 GB เต็ม (มีโปรแกรมอื่นใช้การ์ดจอ เช่นเกม) | ปิดโปรแกรมนั้น แล้ว `/retry` |
| ภาพไม่ตรงบท | SDXL/Animagine วาดพลาด | กด **ทำใหม่** (สุ่มใหม่ทั้งตอน) หรือแก้ `image_prompt` ของช็อตนั้นในไฟล์เรื่องก่อนกด · เลือกภาพเอง: ดูข้อ 6 |
| ภาพสัดส่วนเพี้ยน | โมเดลวาด | ตรวจว่า `story.image_model.repo` เป็น `cagliostrolab/animagine-xl-4.0` และ `lightning: false` |
| ไม่ผ่าน QC | ยาวเกิน/สั้นไป/เงียบนาน | ดูคลิปที่บอทส่งมา ถ้าใช้ได้กด **โพสต์** ได้เลย · ถ้าไม่ได้: นิทานยาวเกิน 90 วิ ตัดคำบรรยายในไฟล์เรื่อง หรือ `tts.rate: "+10%"` แล้วกด **ทำใหม่** |
| WSL กิน RAM ใน Task Manager | cache ไฟล์โมเดล | ปกติ · `.wslconfig` ตั้ง `autoMemoryReclaim=dropCache` แล้ว (มีผลหลัง `wsl --shutdown`) |
| ดิสก์ C: เต็ม | WSL ไฟล์ vhdx โต | ลบ `data/jobs/<เลข>` ของงานที่โพสต์แล้ว · โมเดลอยู่ D: (`story.models_dir`) |

**รีเซ็ตงานที่พังหนัก:** `/cancel <เลข>` แล้วสร้างใหม่ (`/story <ตอน>` ได้ เพราะงานที่ยกเลิกไม่นับ)

---

## 5. ตั้งค่า (`config.yaml`) — แก้แล้วต้อง `systemctl --user restart autovideo-bot`

| ค่า | ใช้ทำอะไร |
|---|---|
| `channel.niche / tone / audience` | บอก Gemini ว่าช่องแนวไหน (สำหรับคลิปความรู้) |
| `video.min_seconds / max_seconds` | ความยาวคลิปความรู้ที่ QC ยอมรับ |
| `llm.model` | รุ่น Gemini |
| `tts.voice / rate` | เสียงพากย์ (`th-TH-NiwatNeural` ชาย) ความเร็ว เช่น `"+10%"` |
| `images.media` | คลิปความรู้: `video` (คลิป Pixabay ก่อน) หรือ `photo` |
| `youtube.privacy` | `private` (แนะนำ) / `unlisted` / `public` |
| `youtube.category_id` | หมวดคลิปความรู้ (22 People&Blogs, 27 Education) นิทานใช้ 24 (Entertainment) จากไฟล์เรื่อง |
| `music.volume` | ความดังเพลง (0.08 ≈ เบากว่าเสียงพากย์ ~12 dB) เพลงสุ่มจาก `assets/music/*.mp3` |
| `story.series` | รายการไฟล์เรื่องที่ `/story` และ 08:00 หยิบตอนถัดไป |
| `story.image_model` | โมเดลวาด (`repo`, `steps`, `cfg`, `negative`) |
| `story.candidates` | วาดกี่แบบต่อช็อต (3) ให้ AI เลือก |
| `story.ai_motion` | `false` = ใช้ 2.5 มิติทุกช็อต (เร็วกว่ามาก) |
| `story.max_seconds` | ความยาวสูงสุดต่อตอน (90) |
| `limits.max_jobs_per_day` | งานต่อวัน |

เวลาตั้งรอบ 08:00: แก้ `OnCalendar=` ใน `scripts/install_services.sh` แล้วรันสคริปต์ใหม่
ไฟล์ลับอยู่ใน `.env` (คีย์ Gemini, Pixabay, Telegram) — ห้ามส่งให้ใคร ไม่ถูกเก็บเข้า git

---

## 6. นิทาน: ไฟล์เรื่อง และการทำเรื่องใหม่

ไฟล์ `drafts/stories/<ชื่อ>.json` หนึ่งเรื่องต่อไฟล์:

```jsonc
{
  "series": "ระบบย้อนเวลา 99 ครั้ง",            // ชื่อเรื่อง (ขึ้นในชื่อคลิป)
  "style": "anime style, ... masterpiece, ...",   // ลายเส้น ต่อท้ายทุกภาพ (อังกฤษ)
  "characters": {
    "ton": {"look": "คำบรรยายยาว (ให้ Gemini อ่าน)", "tag": "1boy, solo, ... (ให้ตัววาดใช้ ภาษาอังกฤษ สั้น)"}
  },
  "parts": [                                       // ตอนที่มีบทแล้ว
    {"part": 1, "title": "เลเวลหนึ่ง", "shots": [
      {"id": 1, "narration": "คำบรรยายไทย (≤45 ตัวอักษร)",
       "image_prompt": "ฉาก ท่าทาง แสง ภาษาอังกฤษ ไม่บรรยายหน้าตาตัวละคร",
       "characters": ["ton"],                      // ตัวแรก = ตัวหลัก ใส่หน้าตาให้เฉพาะตัวนี้
       "motion": "ai"}                             // ai = LTX ขยับจริง (~6 ช็อต/ตอน), parallax = 2.5 มิติ
    ]}
  ],
  "outline": [{"part": 4, "title": "...", "summary": "..."}]   // ตอนที่ยังไม่มีบท: Gemini เขียนให้ตอนถึงคิว
}
```

**เคล็ดลับให้ภาพออกมาดี**
- ช็อตละ 1 ตัวละครหลัก — 2 คนในภาพ ตัววาดจะสลับเสื้อผ้า/อายุกัน
- `tag` ใส่สิ่งที่ต้องเหมือนทุกช็อต (ทรงผม สีผม ชุด) — เสื้อฮู้ดเทาของต้นจำง่ายเพราะเหตุนี้
- ฉากไม่มีคน ลงท้าย `no humans`
- คำบรรยายใช้ตัวเลขเป็นคำอ่าน ("เก้าสิบแปด") เสียงพากย์จะอ่านถูก
- ตอนละ ~18 ช็อต ≈ 60–70 วินาที

**เริ่มเรื่องใหม่**
1. คัดลอกไฟล์เรื่องเดิมเป็นชื่อใหม่ แก้ `series`, `style`, `characters`, เขียน `parts` ตอนแรกเอง (หรือเว้น `parts: []` แล้วเขียนแค่ `outline` ให้ครบทุกตอน — Gemini จะเขียนทุกตอนให้ และส่งมาให้อนุมัติก่อนเสมอ)
2. เพิ่ม path ไฟล์ใน `story.series` (เรื่องแรกในรายการที่ยังไม่ครบจะถูกหยิบก่อน)
3. `systemctl --user restart autovideo-bot` แล้ว `/story`

**ดูภาพทุกแบบ** อยู่ใน `data/jobs/<เลข>/shots/shot_XX.cN.png` ตัวที่ AI เลือกคือ `shot_XX.png` (คะแนนอยู่ใน `picks.json`)
ไม่ชอบภาพ → กด **ทำใหม่** ตอนรอยืนยันโพสต์ (วาดใหม่ทั้งตอนด้วย seed ใหม่ บทเดิม)

**ทดลองวาดอย่างเดียว:** `scripts/story_bg.sh drafts/stories/<ไฟล์>.json <ตอน> --draw-only` แล้วดูภาพใน `data/stories/<ไฟล์>/part<ตอน>/shots/`

---

## 7. ไฟล์และโฟลเดอร์

| ที่อยู่ | คืออะไร |
|---|---|
| `config.yaml` | ค่าตั้งทั้งหมด |
| `.env` | คีย์ลับ (ห้ามเผยแพร่) |
| `client_secret.json`, `data/youtube_token.json` | กุญแจ YouTube (ห้ามเผยแพร่) |
| `drafts/*.json` | บทคลิปความรู้ที่เขียนไว้ (`uv run autovideo new --script drafts/honey.json`) |
| `drafts/stories/*.json` | ไฟล์นิทาน |
| `data/app.db` | ฐานข้อมูลงาน (SQLite) |
| `data/jobs/<เลข>/` | ทุกอย่างของงานนั้น: `script.json`, `audio/`, `shots/`, `images/`, `final.mp4`, `qc.json`, `youtube.json` |
| `data/logs/` | `autovideo.log` (งาน), `bot.log`, `daily.log`, `story.log` |
| `D:\autovideo_models\hf` | โมเดล AI ~45 GB (SDXL, Animagine, LTX, T5, CLIP, Depth) โหลดใหม่: `HF_HOME=/mnt/d/autovideo_models/hf uv run python scripts/download_models.py` |
| `assets/music/` | เพลง (`credits.json` = เครดิตที่ต้องใส่ในคำอธิบาย) |
| `src/autovideo/` | โค้ด (ดูข้อ 8) |

**Backup ที่ควรเก็บ:** `.env`, `client_secret.json`, `data/app.db`, `drafts/` (ที่เหลือสร้างใหม่ได้)

---

## 8. แก้โค้ด (สำหรับคนที่เขียนโปรแกรมได้)

| ไฟล์ | หน้าที่ |
|---|---|
| `orchestrator.py` | state machine: สถานะ → ขั้นถัดไป, ปุ่มต่างๆ (`approve_script`, `redo_media`, ...) , `new_story_job` |
| `bot/telegram_bot.py` | คำสั่ง Telegram, ข้อความแจ้งเตือน, `HELP` |
| `db.py` | ตาราง jobs/events (คอลัมน์ใหม่เพิ่มใน `MIGRATIONS` จะ ALTER ให้เอง) |
| `steps/` | ขั้นของคลิปความรู้: script, voice, visuals, render, qc, publish |
| `story/run.py` | สายการผลิตนิทาน 1 ตอน (เรียกขั้นที่ใช้การ์ดจอเป็น process แยก จำกัด RAM 5 GB) |
| `story/sdxl.py` `pick.py` `ltx.py` `parallax.py` | วาด / เลือก / ขยับ AI / 2.5 มิติ |
| `story/write.py` | ให้ Gemini เขียนตอนจากโครงเรื่อง |
| `providers/` | ต่อบริการภายนอก (Gemini, edge-tts, Pixabay, YouTube) และตัวปลอมสำหรับเทสต์ |

ก่อน/หลังแก้: `uv run pytest -q` (ต้องผ่านหมด) แล้ว `systemctl --user restart autovideo-bot`
ทดลองทั้งระบบโดยไม่เรียกบริการจริงและไม่โพสต์จริง: หยุดบอทก่อน แล้ว `uv run autovideo run --dry-run`
