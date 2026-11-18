# autovideo — ระบบผลิตและโพสต์วิดีโอสั้นอัตโนมัติ

AI เขียนบท → ลงเสียง → หาภาพ → ตัดต่อ → ตรวจ QC แล้วรอให้คุณกดยืนยันผ่าน Telegram สองจุด (หลังได้บท และก่อนโพสต์) จึงอัปโหลดขึ้น YouTube Shorts
สเปกเต็มอยู่ใน [PLAN.md](PLAN.md)

## สถานะ (2026-11-16)

**ระบบรันเองได้โดยไม่ต้องมี Claude Code** — คู่มือใช้งานและแก้ปัญหาฉบับเต็ม: **[docs/MANUAL.md](docs/MANUAL.md)**

| เฟส | สถานะ |
|---|---|
| 0 โครงโปรเจกต์ | ✅ |
| 1 เขียนบท (Gemini `gemini-3.6-flash`) | ✅ เขียนผ่าน schema 5/5 |
| 2 เสียงและซับ (edge-tts) | ✅ |
| 3 ภาพ/คลิป Pixabay + ตัดต่อ + เพลง | ✅ |
| 4 ฐานข้อมูล + orchestrator | ✅ ฆ่ากลางทางแล้วทำต่อได้ |
| 5 Telegram (@Short_Video_Pk_bot) | ✅ ใช้บนมือถือจริง |
| 6 YouTube | ✅ อัปโหลด private จริงแล้ว (งาน #3) |
| 7 รันเอง | ✅ service เปิดเองตอน WSL เริ่ม + Windows task เปิด WSL ตอนล็อกอิน + นิทานตอนถัดไปทุกวัน 08:00 |
| นิทานภาพ AI บนการ์ดจอ | ✅ อยู่ในคิวเดียวกัน เรื่อง "ระบบย้อนเวลา 99 ครั้ง" มีบทครบ 12 ตอน |

**ที่ยังค้าง (ไม่บล็อกการใช้งาน)**
- [ ] แนวช่อง `channel.niche / tone / audience` ใน `config.yaml` (ใช้กับคลิปความรู้)
- [ ] OAuth แอปยังเป็นโหมด Testing → ต้อง `uv run autovideo auth youtube` ใหม่ทุก 7 วัน (แก้ถาวร: ทำหน้า privacy policy + homepage แล้ว Publish app)
- [ ] ยื่น YouTube API Audit ถ้าคลิปที่อัปผ่าน API เปลี่ยนเป็นสาธารณะไม่ได้
- [ ] รีสตาร์ท WSL หนึ่งครั้ง (`wsl --shutdown`) ให้ `.wslconfig` ลด RAM มีผล

ตรวจว่าขาดอะไรอยู่ได้ทุกเมื่อ: `uv run autovideo doctor`

## ติดตั้ง

1. ติดตั้ง Python 3.11 ขึ้นไป และ [uv](https://docs.astral.sh/uv/)
2. ติดตั้ง FFmpeg
   - Ubuntu/WSL: `sudo apt install ffmpeg` (เครื่องนี้ใช้ static build 7.0.2 จาก johnvansickle.com ที่ `~/.local/bin` แทน)
   - Windows: `winget install ffmpeg`
3. ในโฟลเดอร์โปรเจกต์ รัน `uv sync`
4. ทำตาม "สิ่งที่คุณต้องทำ" ด้านบน
5. ฟอนต์ซับ `Kanit-Bold.ttf` (สัญญาอนุญาต OFL) อยู่ใน `assets/fonts/` แล้ว อยากเปลี่ยนให้วางไฟล์ `.ttf` อื่นแทน

**รันทุกคำสั่งจากโฟลเดอร์โปรเจกต์เสมอ**

## ใช้งานประจำวัน

เปิดระบบ (ให้ค้างไว้):

```
uv run autovideo run
```

แล้วใช้ Telegram:

| คำสั่ง | ทำอะไร |
|---|---|
| `/new หัวข้อ` | สร้างงานใหม่ ไม่ใส่หัวข้อ AI จะเลือกเอง โดยเลี่ยง 30 หัวข้อล่าสุด |
| `/status` | ดูงานล่าสุด 10 งาน |
| `/cancel 5` | ยกเลิกงาน #5 |
| `/retry 5` | ลองงาน #5 ที่ล้มเหลวใหม่ |

บอทจะส่งข้อความมาเองเมื่อ:
- **ได้บทแล้ว:** ปุ่ม อนุมัติ / เขียนใหม่ (สูงสุด 3 รอบ) / แก้ไข (พิมพ์สิ่งที่อยากแก้ตามมา) / ยกเลิก
- **ได้คลิปแล้ว:** ส่งวิดีโอ + ผล QC พร้อมปุ่ม โพสต์ / ทำใหม่ (ทำเสียงและภาพใหม่ ไม่ใช้ภาพเดิม) / ยกเลิก
- **ไม่ผ่าน QC, งานล้มเหลว, โควตา AI หมด, อัปโหลดเสร็จ**

กดปุ่มได้ครั้งเดียว หลังกดข้อความจะเปลี่ยนเป็นสิ่งที่เลือก บอทตอบเฉพาะ `TELEGRAM_OWNER_CHAT_ID` คนอื่นส่งมาจะไม่สนใจ
วิดีโออัปโหลดเป็น **private** บอทจะส่งลิงก์ YouTube Studio ให้กดเผยแพร่เอง (เปลี่ยนเป็นอัตโนมัติได้ที่ `youtube.privacy: public`)

### ทดสอบ Telegram (เฟส 5) โดยไม่เรียก AI จริงและไม่โพสต์จริง

```
uv run autovideo run --dry-run
```

ใช้ตัวปลอมทั้งหมด (บทตัวอย่าง เสียงบี๊บ พื้นหลังสี อัปโหลดปลอม) ส่ง `/new ทดสอบ` แล้วลองกดทุกปุ่ม
**สำคัญ:** งานจาก dry-run อยู่ในฐานข้อมูลเดียวกับงานจริง ทดสอบเสร็จให้ `/cancel` ทิ้งให้หมด ก่อนเปิดแบบจริง

### ใช้บทที่เขียนไว้แล้ว (ไม่ต้องมีคีย์ Gemini)

มีบทสำเร็จ 16 เรื่องใน [drafts/](drafts/README.md):

```
uv run autovideo new --script drafts/honey.json
```

### ไม่มี Telegram ก็ใช้จาก terminal ได้

```
uv run autovideo new --topic "หัวข้อ"   # สร้างงาน
uv run autovideo work                   # ตัวทำงาน (ไม่มี bot) --once = ทำจนหมดแล้วหยุด
uv run autovideo jobs                   # ดูสถานะ
uv run autovideo approve 5              # อนุมัติบท หรืออนุมัติโพสต์ แล้วแต่งานรออะไร
uv run autovideo rewrite 5 | revise 5 "ข้อความ" | redo 5 | cancel 5 | retry 5
```

## ตั้งเวลาให้ทำงานเอง (เฟส 7) — ติดตั้งแล้ว

| ตัว | ทำอะไร | ติดตั้ง/ติดตั้งใหม่ |
|---|---|---|
| `autovideo-bot.service` (systemd ผู้ใช้) | บอท + ตัวทำงาน เปิดเองตอน WSL เริ่ม ล่มแล้วเปิดใหม่ใน 30 วิ | `scripts/install_services.sh` |
| `autovideo-daily.timer` | ทุกวัน 08:00 รัน `autovideo story-next` ใส่นิทานตอนถัดไปลงคิว (ถ้าเครื่องปิดตอน 08:00 จะทำตอนเปิด) | `scripts/install_services.sh` |
| Windows Task `AutoVideo-KeepWSL` | ล็อกอิน Windows แล้วเปิด WSL ค้างไว้ (ไม่อย่างนั้น WSL ปิดเองเมื่อไม่มีหน้าต่าง) | `scripts/install_windows_keepalive.ps1` |

อยากให้มีคลิปความรู้อัตโนมัติด้วย: เพิ่ม timer อีกตัวที่รัน `autovideo new` (ดูวิธีแก้ unit ใน [docs/MANUAL.md](docs/MANUAL.md) ข้อ 3)
ระบบจำกัดไม่เกิน `limits.max_jobs_per_day` งานต่อวันอยู่แล้ว · log อยู่ที่ `data/logs/`

## คำสั่งทีละขั้น (สำหรับทดสอบ)

```
uv run autovideo script --topic "หัวข้อ"     # บท -> data/jobs/<เวลา>/script.json
uv run autovideo voice   --job <โฟลเดอร์>
uv run autovideo visuals --job <โฟลเดอร์>
uv run autovideo render  --job <โฟลเดอร์>
uv run autovideo qc      --job <โฟลเดอร์>
uv run autovideo make --topic "หัวข้อ"        # ทั้งสายจนผ่าน QC ไม่มีจุดยืนยัน ไม่โพสต์
uv run autovideo make --dry-run              # ตัวปลอมทั้งหมด ~10 วินาที
```

ยังไม่มีคีย์ Gemini? ใช้บทตัวอย่าง:
`mkdir -p data/jobs/sample && cp tests/fixtures/script_sleep.json data/jobs/sample/script.json && uv run autovideo make --job data/jobs/sample`

ตรวจเกณฑ์เฟส 1: `for i in 1 2 3 4 5; do uv run autovideo script --topic "ประโยชน์ของการนอนหลับ" || break; sleep 2; done`

## รันเทสต์

```
uv run pytest
```

## การตัดสินใจ

**ทั่วไป**
- ใช้ `uv` จัดการ dependency; CLI ใช้ `argparse` ของ Python เอง
- `config.yaml` และ `.env` อ่านจากโฟลเดอร์ที่รันคำสั่ง
- เทสต์ที่ต้องใช้ FFmpeg ข้ามอัตโนมัติถ้าเครื่องไม่มี FFmpeg

**บท (Gemini)**
- ใช้ `google-genai` ส่ง JSON schema ให้ Gemini บังคับรูปแบบ แล้วตรวจซ้ำด้วย `jsonschema`
- ความยาวชื่อคลิป (70) และ `visual_query` ภาษาอังกฤษ ตรวจในโค้ด ไม่ใส่ใน schema ที่ส่ง Gemini เพราะไม่แน่ใจว่ารองรับ `maxLength`
- ไม่ตรวจจำนวนคำ 90–150 คำ (ภาษาไทยนับคำไม่แน่นอน) ขั้นเสียงตรวจความยาวเป็นวินาทีแทน
- Gemini ตอบ 429/500/503 รอ 15, 30, 60 วินาทีแล้วลองใหม่; ถ้า 429 ยังไม่หาย orchestrator เลื่อนงานไปพรุ่งนี้ 00:05 และแจ้งเตือน
- ตรวจคีย์ Gemini ตอนเรียกใช้จริง งานที่มีบทแล้วจึงรันได้โดยไม่ต้องมีคีย์
- "แก้ไข" ส่งบทเดิมทั้ง JSON พร้อมคำสั่ง (`prompts/script_revise.md`) ไม่จำกัดจำนวนครั้ง; "เขียนใหม่" เก็บบทเก่าไว้เป็น `script.rejectedN.json`

**เสียงและซับ**
- เสียงตั้งต้น `th-TH-NiwatNeural` เพราะ `th-TH-PremwadeeNeural` ไม่ส่งเสียงกลับมา (ทดสอบ 2026-11-12)
- ความยาวเสียงแต่ละซีนเก็บใน `scene_XX.words.json` (`duration`) ไม่แก้ `script.json` ที่อนุมัติแล้ว
- ซับตัดคำด้วย pythainlp (`newmm`) ขึ้นบรรทัดใหม่ทุกช่องว่าง บรรทัดละไม่เกิน 20 ตัวอักษร ไม่นับสระบน/ล่างและวรรณยุกต์ คำเดียวที่ยาวเกินไม่ถูกตัด
- เวลาแต่ละบรรทัดใช้เวลาของคำแรกจาก edge-tts; `subs.ass` สร้างในขั้น voice
- ชื่อฟอนต์มาจากไฟล์ `.ttf` ตัวแรกใน `assets/fonts/` เช่น `Kanit-Bold.ttf` → `Kanit`
- edge-tts ใช้ไม่ได้ → งานลองใหม่ 3 ครั้งแล้ว FAILED และแจ้ง Telegram พร้อมข้อความ error (ยังไม่มี TTS สำรอง)

**ภาพและตัดต่อ**
- ไม่มีคีย์ Pixabay / หาภาพไม่เจอ / เน็ตล่ม → พื้นหลังสีพร้อม `visual_note` งานไม่ล้ม (`credits.json` ของซีนนั้นเป็น `null`)
- ใช้ Pixabay แทน Pexels (เจ้าของเลือก) ภาพแนวตั้งยาวสุด 1280px แล้วขยาย/ครอปเป็น 1080x1920 ตอนตัดต่อ
- ข้อความบนพื้นหลังสีวาดด้วย libass เพราะ `drawtext` ของ FFmpeg ตัวนี้วางสระ/วรรณยุกต์ไทยไม่ถูก
- ซูมสลับเข้า/ออก 12% ขยายภาพ 2 เท่าก่อนซูมกันภาพสั่น; จำนวนเฟรมปัดจากเวลาสะสม ภาพกับเสียงไม่เลื่อนกัน
- เพลงประกอบ: ไฟล์ `.mp3` แรกใน `assets/music/` ดัง 12% วนตลอดคลิป
- QC: ช่วงเงียบวัดที่ -40 dB, ตรวจ codec H.264 + AAC; ไฟล์เกิน 50 MB สร้าง `preview.mp4` กว้าง 540 ไว้ส่ง Telegram

**ฐานข้อมูลและ orchestrator**
- เพิ่มสถานะนอกสเปก 2 ตัว: `REVISING` (กำลังแก้บทตามคำสั่ง) และ `PUBLISH_APPROVED` (กดโพสต์แล้ว รออัปโหลด) เพื่อให้ปุ่มแค่เปลี่ยนสถานะ ส่วนงานหนักให้ orchestrator ทำ
- เพิ่มคอลัมน์นอกสเปกใน `jobs`: `revise_note`, `next_attempt_at` (เวลาลองใหม่), `notified_status` (ส่งแจ้งเตือนสถานะนี้แล้วหรือยัง ระบบล่มแล้วเปิดใหม่ก็ส่งต่อได้)
- การเปลี่ยนสถานะทุกครั้งเช็กสถานะเดิมก่อน กดปุ่มซ้ำหรือกดหลังงานเปลี่ยนไปแล้วจะไม่มีผล
- ล้มเหลว: รอ 30, 60 วินาทีแล้วลองใหม่ ครบ `limits.max_retries` (3) เป็น FAILED; `/retry` กลับไปขั้นที่ล้ม
- "ทำใหม่" ลบเสียง/ภาพ/วิดีโอ แล้วจดรหัสภาพเดิมใน `excluded_images.json` เพื่อไม่ให้ได้ภาพเดิม
- งานเดียวทำทีละขั้น ทีละงาน ตามลำดับงานที่สร้างก่อน
- โฟลเดอร์งานใช้เลขงาน: `data/jobs/<id>/`; คำสั่งทดสอบ `script`/`make` ที่ไม่มีเลขงานใช้วันเวลาแทน

**YouTube**
- ตั้ง `status.containsSyntheticMedia = true` เมื่อ `mark_synthetic: true` (ตรวจชื่อฟิลด์จาก discovery document ของ YouTube API 2026-11-12)
- เพิ่ม `youtube.made_for_kids: false` ใน config เพราะ YouTube บังคับให้ระบุ
- เครดิตช่างภาพ Pixabay ต่อท้ายคำอธิบายคลิป
- OAuth ใช้ port 8765 ไม่เปิดเบราว์เซอร์เอง (WSL ไม่มีเบราว์เซอร์) ให้คัดลอกลิงก์ไปเปิดใน Windows; token เก็บที่ `data/youtube_token.json`
- อัปโหลดสำเร็จจะเขียน `youtube.json` ทันที งานเดียวกันไม่อัปโหลดซ้ำ

**ตั้งเวลา**
- ไม่ได้ทำตัวตั้งเวลาในโปรแกรม ใช้ cron / Task Scheduler สั่ง `autovideo new` แทน (ง่ายกว่าและตรงกับสเปก)
- `autovideo run` รัน bot และตัวทำงานในโปรเซสเดียว (ตัวทำงานอยู่ใน thread แยก)

### ภาพเคลื่อนไหวและเพลง (2026-11-13)
- `images.media: video` → แต่ละซีนหาคลิปสั้นจาก Pixabay ก่อน ไม่เจอค่อยใช้ภาพนิ่ง ไม่เจออีกใช้พื้นหลังสี คลิปส่วนใหญ่เป็นแนวนอน จึงครอปตรงกลางเป็น 9:16 และวนซ้ำถ้าสั้นกว่าซีน เปลี่ยนกลับเป็นภาพนิ่งได้ด้วย `media: photo`
- เลือกไฟล์คลิปที่สูง ≥1080px และเล็กที่สุด (ไม่โหลด 4K) ทิ้งเสียงในคลิป
- เพลง: สุ่ม 1 เพลงต่อคลิปจาก `assets/music/*.mp3` จำไว้ใน `music.json` ของงาน เฟดออก 1.5 วินาทีท้าย ความดัง `music.volume` (0.08 ≈ เบากว่าเสียงพากย์ ~12 dB)
- เพลงตั้งต้น 5 เพลงของ Kevin MacLeod (incompetech.com, CC BY 4.0) เครดิตใน `assets/music/credits.json` ต่อท้ายคำอธิบายคลิปให้อัตโนมัติ (สัญญาอนุญาตบังคับ) ไฟล์ mp3 ไม่เข้า git เพราะใหญ่ ถ้าย้ายเครื่องต้องโหลดใหม่หรือวางเพลงของตัวเอง (เพลงที่ไม่ต้องให้เครดิต ไม่ต้องใส่ใน credits.json)
- Pixabay Music ไม่มี API และกันบอทดาวน์โหลด, FreePD ปิดตัวแล้ว จึงใช้ incompetech

### นิทานภาพ AI บนเครื่อง (2026-11-13)
- คำสั่ง: `uv sync --extra gpu` (ครั้งแรก), `uv run python scripts/download_models.py` (~40 GB ไปที่ `story.models_dir`), แล้ว `scripts/story_bg.sh drafts/stories/khao_phan.json 1 --draw-only` → เลือกภาพ (`shots/shot_XX.cN.png` คัดลอกทับ `shot_XX.png`) → `scripts/story_bg.sh drafts/stories/khao_phan.json 1` ดูความคืบหน้า `tail -f data/logs/story.log`
- ภาพ: SDXL-Lightning 8 สเต็ป (~8 วิ/ภาพ, 3 แบบต่อช็อต) น้ำหนัก UNet เก็บแบบ fp8 โหลดตรงเข้าการ์ดจอ คำสั่งวาดใส่ตัวละครหลักแค่คนเดียว เพราะ SDXL สลับลักษณะเมื่อบรรยายหลายคน
- ขยับ: ช็อต `motion: ai` ใช้ LTX-Video 2B 0.9.8 distilled (~1.5 นาที/ช็อตหลังโหลดโมเดล ~2.5 นาที) T5 บีบเป็น 4-bit ครั้งเดียวเก็บไว้ที่ `t5-xxl-nf4` ช็อตอื่นใช้ภาพ 2.5 มิติจาก Depth-Anything V2 Small ถ้า LTX ล้ม ระบบใช้ 2.5 มิติแทนอัตโนมัติ
- WSL มี RAM ~7.6 GB: ทุกขั้นที่ใช้การ์ดจอรันแยก process ใต้ `systemd-run --scope MemoryMax=5G` และทั้งตอนรันเป็น user service (`autovideo-story`) จึงไม่ฆ่า terminal/Claude Code เมื่อ RAM เต็ม (เคยเกิดจริง 2 ครั้งก่อนแก้)
- สัญญาอนุญาต: SDXL/Lightning OpenRAIL++, Depth-Anything Small Apache-2.0, LTX-Video Open Weights (ใช้เชิงพาณิชย์ได้ถ้ารายได้ < $10M/ปี และต้องแจ้งว่าสร้างด้วย AI ซึ่งคำอธิบายคลิปและ `containsSyntheticMedia` ทำให้แล้ว)
