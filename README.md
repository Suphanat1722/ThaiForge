# ThaiForge

ระบบแปลไฟล์ CSV สำหรับงานเกมด้วย Gemini, AI Glossary และ durable background worker
ที่รองรับ pause/resume, retry และแปลใหม่เฉพาะแถวที่ได้รับผลกระทบจากการแก้ Glossary

## เริ่มใช้งานบน Windows

1. คัดลอก `.env.example` เป็น `.env` และใส่ `GEMINI_API_KEY`
2. ดับเบิลคลิก `start.cmd` หรือรัน:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
   ```

สคริปต์จะเตรียม Python environment, ติดตั้ง dependency, build หน้าเว็บ และเปิด
`http://127.0.0.1:8000` โดยอัตโนมัติ ข้อมูลทั้งหมดอยู่ในโฟลเดอร์ `storage/`

## Workflow

1. อัปโหลด CSV และตรวจ encoding/delimiter
2. เลือก Source/Target column และภาษา
3. ให้ Gemini สร้าง Glossary แล้วตรวจแก้ก่อนเริ่ม
4. เริ่มแปล ติดตาม progress, pause/resume และ retry แถวที่ล้มเหลว
5. หลังแก้ Glossary ใช้ Local Scan เพื่อเลือกเฉพาะแถวที่ต้องแปลใหม่
6. Export CSV แบบ UTF-8 BOM หรือดาวน์โหลด error report

ระบบแปลครั้งละหนึ่งงาน การปิดแท็บเบราว์เซอร์ไม่หยุด worker แต่การปิดหน้าต่าง
launcher จะหยุด API และ worker; เมื่อเปิดใหม่ งานเดิมสามารถ Resume จาก checkpoint ได้

## การใช้โควต้า Gemini

ระบบจัด batch ตาม token โดยอัตโนมัติและรวมข้อความซ้ำก่อนเรียก Gemini ค่าเริ่มต้น
รองรับสูงสุด 500 ข้อความไม่ซ้ำต่อ request ภายใต้งบ input 120,000 และ output
45,000 tokens ผลแปลใน cache สามารถใช้ข้ามงานได้เมื่อภาษา Glossary และ Style
ตรงกันทุกประการ

ข้อผิดพลาดชั่วคราวจะลองใหม่อัตโนมัติสูงสุดหนึ่งครั้ง ส่วนข้อผิดพลาดถาวรจะไม่ถูก
นำกลับเข้าคิวโดยปุ่ม Retry รวม เพื่อไม่ใช้โควต้าโดยไม่จำเป็น เมื่อโควต้ารายวันเต็ม
ระบบยังคง Pause และ Resume อัตโนมัติตามเดิม

## พัฒนาและทดสอบ

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
cd frontend
npm.cmd install
npm.cmd run build
```

API documentation ขณะระบบทำงานอยู่ที่ `http://127.0.0.1:8000/docs`

## โครงสร้างโปรเจกต์

```text
backend/
  app/             FastAPI, worker, database และบริการ Gemini
  app/migrations/  SQLite migrations
frontend/
  src/             React application
scripts/           สคริปต์เปิดระบบบน Windows
tests/             ชุดทดสอบ backend และ workflow
docs/              เอกสารสเปกและเอกสารประกอบ
storage/           ฐานข้อมูล ไฟล์งาน และ log ที่สร้างขณะใช้งาน
```
