# แผนโครงการ: ระบบผลิตและโพสต์วิดีโอสั้นอัตโนมัติ (มีคนกดยืนยัน)

เอกสารนี้เป็นสเปกสำหรับให้ Claude Code สร้างระบบทีละเฟส อ่านทั้งไฟล์ก่อนเริ่มเขียนโค้ด

## 1. เป้าหมาย

ระบบที่ AI ทำงานทั้งสาย ตั้งแต่เขียนเนื้อเรื่อง ลงเสียงพากย์ ทำภาพเคลื่อนไหว ตัดต่อ จนถึงโพสต์วิดีโอ โดยเจ้าของระบบมีหน้าที่แค่กดยืนยันผ่าน Telegram สองจุด คือหลังได้บท และก่อนโพสต์

เกณฑ์ความสำเร็จของเวอร์ชันแรก:

- ผลิตได้วันละ 1–2 คลิป โดยไม่มีค่าใช้จ่าย
- คนใช้เวลาตรวจและกดยืนยันไม่เกิน 2 นาทีต่อคลิป
- งานที่ล้มกลางทางทำต่อจากขั้นที่ค้างได้ ไม่ต้องเริ่มใหม่

## 2. สมมติฐานตั้งต้น (แก้ได้ใน config)

| หัวข้อ | ค่าตั้งต้น |
|---|---|
| แพลตฟอร์ม | YouTube Shorts ที่เดียว |
| รูปแบบวิดีโอ | แนวตั้ง 1080x1920, 30 fps, ยาว 30–60 วินาที |
| ภาษา | ไทย |
| สไตล์ภาพ | ภาพนิ่งเคลื่อนไหว (ซูม/แพน) พร้อมซับไตเติล |
| เครื่องที่รัน | คอมของเจ้าของระบบ |
| งบ | 0 บาท |

แนวคอนเทนต์ยังไม่ได้กำหนด ให้เก็บเป็นค่าใน `config.yaml` (`channel.niche`, `channel.tone`, `channel.audience`) และให้ prompt อ่านจากตรงนั้น

## 3. ข้อจำกัดที่ต้องออกแบบรองรับ

1. **ทุกบริการภายนอกต้องสลับได้** แต่ละขั้นมี interface กลาง และมี provider อยู่หลัง interface เพราะบริการฟรีเปลี่ยนเงื่อนไขหรือหยุดให้บริการได้ทุกเมื่อ
2. **โควตา Gemini ฟรีจำกัดต่อวัน** และต่างกันตามรุ่นและบัญชี ห้าม hardcode ชื่อรุ่นหรือตัวเลขโควตา ให้อยู่ใน config และต้องจัดการ error 429 ด้วยการรอแล้วลองใหม่
3. **edge-tts ไม่ใช่ API ทางการ** ต้องมี fallback อย่างน้อยหนึ่งตัวในอนาคต ตอนนี้ให้แจ้งเตือนเข้า Telegram เมื่อใช้ไม่ได้
4. **YouTube อาจล็อกวิดีโอเป็น private** สำหรับโปรเจกต์ API ที่ยังไม่ผ่านการตรวจของ Google ให้อัปโหลดเป็น private เป็นค่าตั้งต้น และส่งลิงก์ YouTube Studio ให้เจ้าของกดเผยแพร่เอง จนกว่าจะตั้งค่า `youtube.privacy: public`
5. **ห้ามโพสต์โดยไม่มีการยืนยัน** ไม่มีโหมดข้ามการยืนยันขั้นโพสต์ในเวอร์ชันแรก
6. **ความลับทั้งหมดอยู่ใน `.env`** และไฟล์ token ห้าม commit

## 4. เครื่องมือที่ใช้

| ขั้น | เครื่องมือ | หมายเหตุ |
|---|---|---|
| ภาษา | Python 3.11+ | |
| เขียนบท | Gemini API (free tier) | คีย์จาก Google AI Studio |
| เสียงพากย์ | `edge-tts` | ตรวจรายชื่อเสียงไทยด้วย `edge-tts --list-voices` |
| ตัดคำไทย | `pythainlp` | ใช้แบ่งบรรทัดซับไตเติล |
| ภาพ | Pexels API (ฟรี ต้องขอคีย์) | provider แรก |
| ตัดต่อ | FFmpeg เรียกผ่าน subprocess | |
| ยืนยัน | `python-telegram-bot` | ใช้ long polling ไม่ต้องเปิดพอร์ต |
| โพสต์ | YouTube Data API v3 + OAuth | `google-api-python-client` |
| ฐานข้อมูล | SQLite | |
| ตั้งเวลา | cron หรือ Task Scheduler | |
| ฟอนต์ซับ | ฟอนต์ไทยสัญญาอนุญาต OFL เช่น Kanit หรือ Sarabun | เก็บใน `assets/fonts/` |

ก่อนใช้ไลบรารีใด ให้ตรวจเอกสารเวอร์ชันล่าสุดก่อน อย่าเดา signature ของฟังก์ชัน

## 5. สถาปัตยกรรม

```
[ตัวตั้งเวลา / คำสั่ง /new ใน Telegram]
            |
            v
      [Orchestrator]  <---->  [SQLite: jobs, events, topics]
            |
   1. script   -> Gemini           -> script.json
   -- รอยืนยันบท (Telegram) --
   2. voice    -> edge-tts         -> scene_XX.mp3 + เวลาแต่ละคำ
   3. visuals  -> Pexels           -> scene_XX.jpg
   4. render   -> FFmpeg           -> final.mp4
   5. qc       -> ตรวจอัตโนมัติ     -> qc.json
   -- รอยืนยันโพสต์ (Telegram) --
   6. publish  -> YouTube          -> video_id
```

Orchestrator เป็น state machine ที่อ่านสถานะจากฐานข้อมูล ทำขั้นถัดไปหนึ่งขั้น บันทึกผล แล้ววนต่อ การรอยืนยันคือการหยุดที่สถานะรอ แล้วปล่อยให้ Telegram bot เป็นคนเปลี่ยนสถานะเมื่อมีการกดปุ่ม

### สถานะของงาน

```
NEW
 -> SCRIPT_DRAFTED
 -> AWAITING_SCRIPT_APPROVAL   (กด: อนุมัติ / เขียนใหม่ / แก้ไข / ยกเลิก)
 -> SCRIPT_APPROVED
 -> VOICE_DONE
 -> VISUALS_DONE
 -> RENDERED
 -> QC_PASSED                  (ถ้าไม่ผ่าน: QC_FAILED แล้วแจ้งเตือน)
 -> AWAITING_PUBLISH_APPROVAL  (กด: โพสต์ / ทำใหม่ / ยกเลิก)
 -> PUBLISHED

สถานะปลายทางอื่น: CANCELLED, FAILED
```

กติกา:

- แต่ละขั้นต้อง idempotent คือรันซ้ำแล้วได้ผลเดิม ถ้าไฟล์ผลลัพธ์มีอยู่แล้วและสมบูรณ์ให้ข้าม
- ล้มเหลวให้ลองใหม่สูงสุด 3 ครั้งแบบเว้นช่วงเพิ่มขึ้น แล้วจึงเป็น FAILED และแจ้งเข้า Telegram
- "เขียนใหม่" ย้อนไป NEW พร้อมเพิ่มตัวนับ จำกัด 3 รอบต่องาน
- "แก้ไข" รับข้อความคำสั่งจากเจ้าของ แล้วส่งบทเดิมพร้อมคำสั่งให้ Gemini แก้เฉพาะส่วน
- "ทำใหม่" ที่ขั้นโพสต์ ย้อนไป SCRIPT_APPROVED แล้วทำเสียงและภาพใหม่

## 6. โครงสร้างโฟลเดอร์

```
project/
  PLAN.md
  README.md
  pyproject.toml
  config.yaml
  .env.example
  .gitignore
  assets/
    fonts/
    music/
  prompts/
    script_system.md
    script_revise.md
  src/autovideo/
    __init__.py
    config.py          # โหลด config.yaml และ .env
    db.py              # schema และฟังก์ชันอ่านเขียน
    models.py          # dataclass: Job, Script, Scene
    orchestrator.py    # state machine
    cli.py             # คำสั่งรันทีละขั้นและรันทั้งสาย
    steps/
      script.py
      voice.py
      visuals.py
      render.py
      qc.py
      publish.py
    providers/
      llm_gemini.py
      tts_edge.py
      images_pexels.py
      upload_youtube.py
    bot/
      telegram_bot.py
  data/                # ไม่ commit
    app.db
    jobs/<job_id>/
      script.json
      audio/scene_01.mp3
      audio/scene_01.words.json
      images/scene_01.jpg
      subs.ass
      final.mp4
      qc.json
  tests/
```

## 7. รูปแบบข้อมูล

### script.json

```json
{
  "topic": "หัวข้อของคลิป",
  "title": "ชื่อคลิป ไม่เกิน 70 ตัวอักษร",
  "description": "คำอธิบายใต้คลิป",
  "tags": ["แท็ก1", "แท็ก2"],
  "scenes": [
    {
      "id": 1,
      "narration": "บทพากย์ของซีนนี้ 1-2 ประโยค",
      "visual_query": "english search keywords for stock image",
      "visual_note": "คำอธิบายภาพที่ต้องการ"
    }
  ]
}
```

กติกาของบท: 5–8 ซีน, บทพากย์รวมประมาณ 90–150 คำ, ซีนแรกต้องดึงความสนใจใน 3 วินาที, `visual_query` เป็นภาษาอังกฤษเพราะค้นภาพสต็อกได้ผลดีกว่า ให้ตรวจ JSON กับ schema ทุกครั้ง ถ้าไม่ผ่านให้ขอใหม่

### ตารางในฐานข้อมูล

- `jobs`: id, status, topic, attempt_count, revise_count, error, youtube_video_id, created_at, updated_at
- `events`: id, job_id, from_status, to_status, detail, created_at (บันทึกทุกการเปลี่ยนสถานะ)
- `topics`: id, topic, job_id, created_at (ใช้กันหัวข้อซ้ำ ส่ง 30 หัวข้อล่าสุดเข้า prompt)

### config.yaml (ตัวอย่างหัวข้อ)

```yaml
channel:
  niche: ""
  tone: ""
  audience: ""
  language: th
video:
  width: 1080
  height: 1920
  fps: 30
  min_seconds: 25
  max_seconds: 60
llm:
  provider: gemini
  model: ""          # ใส่ชื่อรุ่น Flash ที่บัญชีใช้ฟรีได้
tts:
  provider: edge
  voice: ""          # เลือกจาก edge-tts --list-voices
  rate: "+0%"
images:
  provider: pexels
youtube:
  privacy: private
  category_id: "22"
  mark_synthetic: true
limits:
  max_jobs_per_day: 2
  max_retries: 3
```

### .env.example

```
GEMINI_API_KEY=
PEXELS_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_OWNER_CHAT_ID=
YOUTUBE_CLIENT_SECRETS_FILE=client_secret.json
```

## 8. สเปกแต่ละขั้น

### 8.1 script

- เข้า: หัวข้อ (ถ้าไม่มีให้ LLM คิดเองจาก niche โดยเลี่ยงหัวข้อใน `topics`)
- ออก: `script.json` ที่ผ่าน schema
- prompt เก็บเป็นไฟล์ใน `prompts/` ไม่ฝังในโค้ด

### 8.2 voice

- สร้างเสียงแยกไฟล์ต่อซีน และเก็บเวลาเริ่มของแต่ละคำจาก edge-tts ลง `words.json`
- วัดความยาวจริงของแต่ละไฟล์ด้วย ffprobe แล้วบันทึกลงข้อมูลซีน ความยาวนี้เป็นตัวกำหนดความยาวภาพ
- ถ้าความยาวรวมเกิน `max_seconds` ให้ fail พร้อมข้อความชัดเจน

### 8.3 visuals

- ค้นภาพแนวตั้งจาก Pexels ด้วย `visual_query` เลือกภาพที่ยังไม่เคยใช้ในงานเดียวกัน
- ถ้าไม่พบภาพ ให้ใช้พื้นหลังสีพร้อมข้อความแทน งานต้องไม่ล้มเพราะหาภาพไม่ได้
- บันทึกชื่อช่างภาพและลิงก์ต้นทางลง `credits.json` เพื่อใส่ในคำอธิบายคลิป

### 8.4 render

- แต่ละซีน: ครอบภาพเป็น 1080x1920 ใส่การซูมช้าๆ ยาวเท่าเสียงของซีน
- ต่อทุกซีน รวมเสียงพากย์ และเพลงประกอบเบาๆ ถ้ามีไฟล์ใน `assets/music/`
- ซับไตเติลสร้างเป็นไฟล์ `.ass` จาก `words.json` ใช้ `pythainlp` ตัดคำ แล้วจัดบรรทัดละไม่เกินประมาณ 20 ตัวอักษร ห้ามตัดกลางคำ
- ออก: `final.mp4` แบบ H.264 + AAC

### 8.5 qc

ตรวจอัตโนมัติและบันทึกลง `qc.json`:

- ความยาวอยู่ในช่วงที่กำหนด
- ความละเอียดและ fps ถูกต้อง
- มีแทร็กเสียง และไม่มีช่วงเงียบยาวเกิน 2 วินาที
- ขนาดไฟล์ไม่เกินขีดจำกัดการส่งไฟล์ของ Telegram bot (ถ้าเกิน ให้สร้างไฟล์พรีวิวความละเอียดต่ำสำหรับส่งตรวจ)

### 8.6 publish

- OAuth แบบ installed app ทำครั้งเดียวด้วยคำสั่ง `autovideo auth youtube` แล้วเก็บ refresh token ในไฟล์
- อัปโหลดแบบ resumable พร้อม title, description, tags และ privacy จาก config
- ถ้า `mark_synthetic: true` ให้ตั้งค่าการเปิดเผยว่าเป็นเนื้อหาที่สร้างด้วย AI ตามฟิลด์ที่ YouTube API รองรับ (ตรวจชื่อฟิลด์จากเอกสารปัจจุบัน)
- บันทึก `youtube_video_id` และส่งลิงก์กลับเข้า Telegram

### 8.7 Telegram bot

- รับคำสั่งจาก `TELEGRAM_OWNER_CHAT_ID` เท่านั้น ข้อความจากคนอื่นให้เพิกเฉย
- คำสั่ง: `/new [หัวข้อ]`, `/status`, `/cancel <job_id>`, `/retry <job_id>`
- ขั้นยืนยันบท: ส่งชื่อคลิปและบทแบ่งซีน พร้อมปุ่ม อนุมัติ / เขียนใหม่ / แก้ไข / ยกเลิก
- ขั้นยืนยันโพสต์: ส่งวิดีโอ ชื่อ คำอธิบาย และผล QC พร้อมปุ่ม โพสต์ / ทำใหม่ / ยกเลิก
- ปุ่มแต่ละชุดกดได้ครั้งเดียว หลังกดให้แก้ข้อความเป็นผลที่เลือก

## 9. เฟสการทำงาน

ทำทีละเฟส จบเฟสแล้วหยุดรายงานผลก่อนขึ้นเฟสถัดไป

### เฟส 0: โครงโปรเจกต์
- สร้างโครงสร้างโฟลเดอร์, `pyproject.toml`, config loader, `.env.example`, `.gitignore`
- **ผ่านเมื่อ:** `autovideo --help` รันได้ และ `autovideo doctor` ตรวจว่ามี FFmpeg และคีย์ครบหรือขาดอะไร

### เฟส 1: เขียนบท
- provider Gemini, ขั้น script, ตรวจ schema
- **ผ่านเมื่อ:** `autovideo script --topic "..."` ได้ `script.json` ที่ผ่าน schema 5 ครั้งติดกัน

### เฟส 2: เสียงและซับ
- provider edge-tts, ขั้น voice, สร้างไฟล์ `.ass`
- **ผ่านเมื่อ:** ได้ไฟล์เสียงครบทุกซีน และซับไม่ตัดกลางคำไทย

### เฟส 3: ภาพและตัดต่อ
- provider Pexels, ขั้น visuals, render, qc
- **ผ่านเมื่อ:** `autovideo make --topic "..."` ได้ `final.mp4` ที่ผ่าน QC ทั้งหมด โดยไม่ต้องแก้มือ

### เฟส 4: ฐานข้อมูลและ orchestrator
- schema, state machine, การลองซ้ำ, การทำต่อจากจุดค้าง
- **ผ่านเมื่อ:** ฆ่าโปรเซสกลางขั้น render แล้วรันใหม่ งานทำต่อจากขั้นเดิมและจบได้

### เฟส 5: Telegram
- bot, ปุ่มยืนยันสองจุด, คำสั่งทั้งหมด
- **ผ่านเมื่อ:** ทำครบวงจรจาก `/new` ถึงสถานะ AWAITING_PUBLISH_APPROVAL ผ่านมือถืออย่างเดียว และทดสอบปุ่ม เขียนใหม่ กับ แก้ไข แล้วทำงานถูก

### เฟส 6: YouTube
- OAuth, อัปโหลด, ส่งลิงก์กลับ
- **ผ่านเมื่อ:** กดปุ่มโพสต์แล้ววิดีโอขึ้นในช่องเป็น private พร้อมข้อมูลครบ

### เฟส 7: ตั้งเวลาและความทนทาน
- คำสั่ง `autovideo run` ที่เปิดทั้ง bot และ orchestrator, ตัวอย่างการตั้ง cron, จำกัดจำนวนงานต่อวัน, log ลงไฟล์
- **ผ่านเมื่อ:** ระบบสร้างงานเองตามเวลา 3 วันติดกันโดยไม่ต้องแตะเครื่อง

### ภายหลัง (ไม่อยู่ในเวอร์ชันแรก)
- provider ภาพแบบ AI หรืออนิเมชั่นจากโค้ด (Remotion/Manim)
- TTS สำรอง
- TikTok และ Instagram
- ดึงสถิติยอดวิวกลับมาปรับหัวข้อ

## 10. การทดสอบ

- unit test สำหรับ: ตรวจ schema ของบท, การแบ่งบรรทัดซับไทย, การเปลี่ยนสถานะของ state machine
- provider ทุกตัวมี fake สำหรับ test เพื่อไม่ให้ test เรียกบริการจริง
- มีคำสั่ง `autovideo make --dry-run` ที่ใช้ fake ทั้งหมดและจบในไม่กี่วินาที

## 11. ความเสี่ยงและการรับมือ

| ความเสี่ยง | การรับมือ |
|---|---|
| ช่องถูกมองว่าเป็นคอนเทนต์ผลิตซ้ำจำนวนมาก | จำกัดวันละ 1–2 คลิป มีคนตรวจทุกคลิป กำหนดแนวและน้ำเสียงเฉพาะใน config |
| โควตา LLM หมดกลางวัน | รอแล้วลองใหม่ ถ้ายังไม่ได้ให้เลื่อนงานไปวันถัดไปและแจ้งเตือน |
| edge-tts ใช้ไม่ได้ | แจ้งเตือนทันที และ interface พร้อมรับ provider ใหม่ |
| ภาพสต็อกไม่ตรงเนื้อหา | เจ้าของกด "ทำใหม่" ได้ และวางแผนเพิ่ม provider ภาพในภายหลัง |
| ลิขสิทธิ์เพลงและภาพ | ใช้เฉพาะไฟล์ที่เจ้าของใส่ใน `assets/music/` เอง และเก็บเครดิตภาพทุกครั้ง |
| token รั่ว | `.env` และไฟล์ token อยู่ใน `.gitignore` ตั้งแต่เฟส 0 |

## 12. คำสั่งสำหรับ Claude Code

1. เริ่มที่เฟส 0 และทำตามลำดับ ห้ามข้ามเฟส
2. จบแต่ละเฟสให้รันเกณฑ์ "ผ่านเมื่อ" จริง แล้วรายงานผลพร้อมสิ่งที่เจ้าของต้องทำเอง เช่น ขอ API key
3. เมื่อเจอสิ่งที่สเปกไม่ได้ระบุ ให้เลือกทางที่ง่ายที่สุดและจดไว้ใน `README.md` หัวข้อ "การตัดสินใจ"
4. ห้ามเพิ่มบริการที่มีค่าใช้จ่าย
5. ห้ามเขียนโค้ดที่ข้ามการยืนยันก่อนโพสต์
6. เขียน `README.md` ให้คนที่ไม่ได้เขียนโค้ดติดตั้งและรันตามได้

## 13. สิ่งที่เจ้าของต้องเตรียมเอง

- [ ] กำหนดแนวคอนเทนต์ น้ำเสียง และกลุ่มผู้ชม ใส่ใน `config.yaml`
- [ ] API key ของ Gemini จาก Google AI Studio และเลือกรุ่นที่ใช้ฟรีได้
- [ ] API key ของ Pexels
- [ ] สร้าง Telegram bot ผ่าน BotFather และหา chat ID ของตัวเอง
- [ ] สร้างโปรเจกต์ Google Cloud เปิด YouTube Data API และสร้าง OAuth client แบบ Desktop
- [ ] ติดตั้ง Python และ FFmpeg
- [ ] เลือกเสียงพากย์ไทยที่ชอบ
