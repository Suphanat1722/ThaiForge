# สเปกระบบ: CSV Auto-Translation System with AI Glossary

## 1. ภาพรวม (Overview)

ระบบเว็บแอปสำหรับแปลไฟล์ CSV แบบอัตโนมัติ โดยใช้ Google AI API (Gemini) เป็นตัวแปล
กระบวนการหลักแบ่งเป็น 5 ขั้นตอน:

```
[1] Upload CSV
      -> [2] AI สร้าง Glossary/Rules
            -> [3] ผู้ใช้ตรวจสอบ/แก้ไข Glossary
                  -> [4] AI แปลทีละแถว (batch, pause/resume ได้)
                        -> [5] Export CSV ผลลัพธ์
```

จุดสำคัญของระบบ: งานแปลต้องรันแบบ **background job** ที่แยกออกจาก request ของหน้าเว็บ
และต้อง **บันทึกสถานะราย row ลง database ทันที** เพื่อให้หยุดกลางทางแล้วกลับมาทำต่อได้
โดยไม่ต้องเริ่มใหม่ทั้งไฟล์

---

## 2. Tech stack ที่แนะนำ

- **Frontend**: React (SPA) — หน้าอัปโหลด, หน้าตาราง glossary (แก้ไขได้), หน้า progress + ปุ่มควบคุม
- **Backend**: Node.js (Express/Fastify) หรือ Python (FastAPI)
- **Job queue / worker**: BullMQ (ถ้าใช้ Node + Redis) หรือ Celery/RQ (ถ้าใช้ Python)
  - งานแปลต้องรันใน worker process แยกจาก web server เพื่อไม่ให้หายเมื่อปิดเบราว์เซอร์
- **Database**: SQLite (ใช้คนเดียว/เริ่มต้น) หรือ PostgreSQL (ถ้าต้องรองรับหลายคน/หลาย job พร้อมกัน)
- **Realtime update**: WebSocket หรือ Server-Sent Events (SSE) สำหรับอัปเดต progress bar แบบ live
  (ถ้าไม่อยากทำ realtime ก่อน ใช้ polling status endpoint ทุก 2-3 วินาทีก็พอสำหรับ MVP)
- **AI**: Google AI API (Gemini) — เรียก 2 แบบ ตามรายละเอียดข้อ 5 และ 6

---

## 3. Database schema

### ตาราง `jobs`
| field | type | หมายเหตุ |
|---|---|---|
| id | string (uuid) | primary key |
| filename | string | ชื่อไฟล์ต้นฉบับ |
| status | enum | `uploaded` \| `generating_glossary` \| `awaiting_review` \| `running` \| `paused` \| `done` \| `failed` |
| source_lang | string | ภาษาต้นฉบับ |
| target_lang | string | ภาษาปลายทาง |
| total_rows | int | จำนวนแถวทั้งหมด |
| completed_rows | int | จำนวนแถวที่แปลเสร็จแล้ว |
| created_at | timestamp | |
| updated_at | timestamp | |

### ตาราง `glossary_entries`
| field | type | หมายเหตุ |
|---|---|---|
| id | string (uuid) | primary key |
| job_id | string (FK) | อ้างถึง jobs.id |
| source_term | string | คำ/วลีต้นฉบับ |
| target_term | string | คำแปลที่กำหนด |
| rule_note | string | บริบท/กฎเพิ่มเติม (เช่น โทนภาษา, ห้ามแปลชื่อเฉพาะ) |
| is_active | boolean | เปิด/ปิดการใช้ entry นี้ |
| created_by | enum | `ai` \| `user` (บอกว่า AI สร้างหรือผู้ใช้แก้/เพิ่มเอง) |

### ตาราง `translation_rows`
| field | type | หมายเหตุ |
|---|---|---|
| id | string (uuid) | primary key |
| job_id | string (FK) | อ้างถึง jobs.id |
| row_index | int | ลำดับแถวใน CSV ต้นฉบับ (ใช้ต่อไฟล์กลับตอน export) |
| source_text | text | ข้อความต้นฉบับ |
| translated_text | text (nullable) | ผลแปล |
| status | enum | `pending` \| `in_progress` \| `done` \| `failed` |
| retry_count | int | จำนวนครั้งที่ retry ไปแล้ว |
| last_error | string (nullable) | ข้อความ error ล่าสุด (ถ้ามี) |
| updated_at | timestamp | |

> หัวใจของ pause/resume อยู่ตรงนี้: worker query หาแถวที่ `status = pending` หรือ `failed`
> (และ retry_count ยังไม่เกิน limit) มาทำทีละ batch แล้ว update สถานะทันทีหลังแปลแต่ละแถวเสร็จ
> ไม่ต้องรอจบทั้งไฟล์ค่อย save

---

## 4. API endpoints (ตัวอย่าง)

```
POST   /api/jobs                     -> อัปโหลด CSV, สร้าง job ใหม่, parse เป็น translation_rows (status=pending)
POST   /api/jobs/:id/generate-glossary  -> เรียก AI วิเคราะห์ CSV แล้วสร้าง glossary_entries
GET    /api/jobs/:id/glossary        -> ดึง glossary entries มาแสดง/แก้ไข
PUT    /api/jobs/:id/glossary/:entryId  -> แก้ไข entry
POST   /api/jobs/:id/glossary/:entryId  -> เพิ่ม entry ใหม่ (ผู้ใช้เพิ่มเอง)
DELETE /api/jobs/:id/glossary/:entryId  -> ลบ entry

POST   /api/jobs/:id/start           -> เริ่ม/สั่งให้ worker เริ่มแปล (status -> running)
POST   /api/jobs/:id/pause           -> ตั้ง flag ให้ worker หยุดหลัง batch ปัจจุบัน (status -> paused)
POST   /api/jobs/:id/resume          -> สั่งให้ worker กลับมาทำต่อ (status -> running)
POST   /api/jobs/:id/retry-failed    -> reset แถวที่ failed กลับเป็น pending แล้วสั่งแปลใหม่

GET    /api/jobs/:id/status          -> ดู progress ปัจจุบัน (total, completed, failed count)
GET    /api/jobs/:id/rows            -> ดูรายละเอียดราย row (ใช้แสดงตาราง preview + error)
GET    /api/jobs/:id/export          -> export เป็นไฟล์ CSV ผลลัพธ์ (export ได้แม้ job ยังไม่เสร็จ 100%)
```

---

## 5. ขั้นตอนสร้าง Glossary (ขั้นตอนที่ 2)

ระบบจำแนกแต่ละคำเป็น `translate`, `transliterate`, `keep` หรือ `mixed`
ก่อนสร้างคำตอบ โดยใช้หลักสากลชุดเดียว ไม่มี preset ผู้ใช้เพิ่มข้อกำหนดเฉพาะโปรเจกต์
แบบไม่บังคับได้ ข้อกำหนดนี้แยกจาก Style Rules และถูกส่งทั้งรอบสกัด candidate
และรอบตรวจด้วยบริบท Cache key ต้องรวมข้อกำหนดจริงและ policy version เสมอ
การเปลี่ยนข้อกำหนดไม่ลบ Glossary หรือคำแปลเดิม และจะแสดงสถานะว่าต้องสร้าง
Glossary ใหม่จึงจะมีผล

1. Backend อ่าน Source ทุกแถว ตัดข้อความซ้ำ และแบ่งเป็น chunk ตามจำนวนแถว/ตัวอักษร
2. ส่งแต่ละ chunk ให้ Gemini สกัด candidate เป็น compact structured output
3. รวม candidate ที่ซ้ำกัน แล้วสแกน Source ทั้งไฟล์ในเครื่องเพื่อรวบรวม:
   - จำนวนครั้งที่พบ
   - ตัวอย่างการใช้ที่แตกต่างกันสูงสุด 4 ตัวอย่างต่อคำ
4. แบ่ง candidate พร้อมบริบทเป็นชุดกระชับ แล้วให้ Gemini ตรวจคำแปลตามหลัก:
   - แปลความหมายเป็นภาษาไทยธรรมชาติเป็นค่าเริ่มต้น
   - ทับศัพท์เฉพาะชื่อบุคคล สถานที่ แบรนด์ และชื่อสมมติ
   - ไม่ถือว่าตัวอักษรขึ้นต้นด้วยตัวใหญ่เป็นชื่อเฉพาะโดยอัตโนมัติ
   - ไม่เดาเพศหรือผู้พูดเมื่อ Source ไม่ให้ข้อมูล
5. คืนค่าเป็น JSON structured output เช่น:
   ```json
   {
     "glossary": [
       { "source_term": "...", "target_term": "...", "note": "..." }
     ]
   }
   ```
6. Cache ทั้งผลสกัดและผลตรวจตาม model, ภาษา, prompt policy และข้อมูลที่ส่ง
7. หากรอบตรวจบริบทล้มเหลว ให้เก็บ candidate รอบสกัดไว้สำหรับตรวจด้วยมือ
8. บันทึกผลลง `glossary_entries` (`created_by = "ai"`)
9. ตั้ง `job.status = awaiting_review` แล้วรอผู้ใช้กดยืนยันหน้า UI

---

## 6. ขั้นตอนแปล (ขั้นตอนที่ 4) — worker loop

```
loop:
  if job.status != "running": stop loop

  rows = SELECT * FROM translation_rows
         WHERE job_id = :id AND status IN ('pending', 'failed')
         AND retry_count < MAX_RETRY
         ORDER BY row_index
         LIMIT BATCH_SIZE

  if rows is empty:
     job.status = "done"
     break

  for row in rows:
    set row.status = "in_progress"
    try:
      translated = call_gemini(row.source_text, glossary, style_rules)
      row.translated_text = translated
      row.status = "done"
    catch transient_error (rate limit / timeout):
      row.retry_count += 1
      row.status = "pending"        # ให้ loop รอบถัดไปหยิบมาทำใหม่ (exponential backoff)
    catch permanent_error:
      row.status = "failed"
      row.last_error = error.message

    save row to DB immediately
    update job.completed_rows

  re-check job.status (paused flag) ก่อนไป batch ถัดไป
```

**หลักการ retry**
- error ชั่วคราว (rate limit, network timeout) → retry อัตโนมัติ ไม่เกิน N ครั้ง ด้วย exponential backoff
- error ถาวร (input ผิดปกติ, content policy) → mark เป็น `failed` ทันที ไม่ retry ซ้ำ ให้ผู้ใช้ดูใน UI แล้วสั่ง retry เองทีหลังได้

---

## 7. หน้า UI ที่ต้องมี

1. **หน้าอัปโหลด** — เลือกไฟล์ CSV, เลือกภาษาต้นทาง/ปลายทาง, กด "เริ่มวิเคราะห์"
2. **หน้า Glossary review** — ตารางแก้ไขได้ (เพิ่ม/ลบ/แก้ term), ปุ่ม "ยืนยันและเริ่มแปล"
3. **หน้า Progress** —
   - progress bar (completed / total)
   - ปุ่ม Pause / Resume
   - ตารางแถวที่ failed พร้อมปุ่ม retry เฉพาะแถว
   - ปุ่ม Export CSV (กดได้แม้ยังแปลไม่ครบ 100%)

---

## 8. งานที่ต้องทำ (task breakdown สำหรับ implement)

- [ ] ตั้ง project skeleton (backend + frontend + DB migration)
- [ ] CSV upload + parse เป็น `translation_rows`
- [ ] Integration กับ Google AI API (Gemini) — ฟังก์ชัน generate glossary
- [ ] Integration กับ Google AI API (Gemini) — ฟังก์ชันแปลทีละแถว/batch พร้อมแนบ glossary
- [ ] Job queue + worker loop (pause/resume/retry ตามข้อ 6)
- [ ] API endpoints ทั้งหมดตามข้อ 4
- [ ] หน้า UI ทั้ง 3 หน้าตามข้อ 7
- [ ] Export CSV กลับให้ตรงลำดับ row เดิม (ใช้ row_index)
- [ ] Error handling + logging
- [ ] ทดสอบ pause กลางทาง แล้ว resume ว่าไม่แปลซ้ำ/ไม่ตกหล่นแถวไหน
