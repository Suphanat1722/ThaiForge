# ThaiForge

เครื่องมือแปลไฟล์ CSV สำหรับงานแปลเกม ใช้ Gemini ช่วยแปลและสร้าง Glossary
โดยเก็บงานทั้งหมดไว้ในเครื่อง

ThaiForge ออกแบบมาสำหรับไฟล์ที่มีข้อความจำนวนมาก งานแปลสามารถหยุดแล้วทำต่อได้
ปิดหน้าเว็บได้โดยไม่ทำให้งานหาย และเมื่อแก้ Glossary ระบบสามารถเลือกแปลใหม่เฉพาะแถว
ที่ได้รับผลกระทบแทนการเริ่มทั้งหมดใหม่

## ความสามารถหลัก

- ตรวจ encoding และ delimiter ของไฟล์ CSV ก่อนเริ่มงาน
- เลือกคอลัมน์ต้นฉบับ คอลัมน์ผลลัพธ์ และภาษาได้เอง
- เลือก Context Columns ได้หลายคอลัมน์ เช่น `character`, `scene`, `note`
- สร้างและแก้ไข Glossary ก่อนแปล
- รองรับ Pause/Resume และเก็บผลลัพธ์ที่แปลสำเร็จแล้วเป็นระยะ
- Retry เฉพาะแถวที่ยังไม่สำเร็จ โดยไม่ Retry ข้อผิดพลาดถาวร
- แก้คำแปลด้วยมือในหน้าตรวจสอบก่อน Export
- Export กลับเป็น CSV โดยคงคอลัมน์และข้อมูลเดิมไว้ครบ
- ใช้ cache ลดการส่งข้อความเดิมไปยัง Gemini ซ้ำ

## สิ่งที่ต้องมี

- Windows 10 หรือ 11
- Python 3.11
- Node.js และ npm
- Gemini API key

## เริ่มใช้งาน

1. Clone โปรเจกต์และเข้าโฟลเดอร์

   ```powershell
   git clone https://github.com/Suphanat1722/ThaiForge.git
   cd ThaiForge
   ```

2. สร้างไฟล์ `.env` จากตัวอย่าง แล้วใส่ API key

   ```powershell
   Copy-Item .env.example .env
   ```

   ```env
   GEMINI_API_KEY=your_api_key_here
   ```

3. เปิด `start.cmd` หรือรันคำสั่งนี้

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
   ```

สคริปต์จะสร้าง virtual environment, ติดตั้ง dependencies, build หน้าเว็บ
และเปิด [http://127.0.0.1:8000](http://127.0.0.1:8000) ให้โดยอัตโนมัติ

ระหว่างที่กำลังแปล สามารถปิดแท็บเบราว์เซอร์ได้ แต่ต้องเปิดหน้าต่าง launcher ไว้
เพราะหน้าต่างนี้ดูแลทั้ง API และ worker

## รูปแบบไฟล์

ขณะนี้รองรับไฟล์ CSV โดยตรง ไฟล์ JSON ต้องแปลงเป็น CSV ก่อนนำเข้า

ตัวอย่าง:

```csv
id,character,scene,source_en,translation_th
event_001,Karen,Heart Event,I love you.,
event_002,Shopkeeper,General,Welcome to my shop!,
```

ในหน้า File Setup ให้เลือก:

- Source Column: `source_en`
- Target Column: `translation_th`
- Context Columns: `character` และ `scene` (เลือกหรือไม่เลือกก็ได้)

ผลการแปลจะเขียนลงใน Target Column ของแถวนั้น ไม่ได้นำไปต่อท้ายข้อความเดิม
ถ้าแถวใดยังแปลไม่สำเร็จ ค่าเดิมใน Target Column จะยังอยู่ตามเดิม

Context ใช้เพื่อช่วยให้โมเดลเข้าใจผู้พูด ฉาก และสถานการณ์เท่านั้น ระบบจะไม่ให้โมเดล
แปลหรือแก้ไขค่า Context และจะไม่ส่งคอลัมน์ที่ไม่ได้เลือกหรือค่าที่ว่าง

## ขั้นตอนการทำงาน

1. อัปโหลด CSV และตรวจ encoding กับ delimiter
2. เลือก Source, Target, Context Columns และภาษา
3. สร้าง Glossary แล้วตรวจคำก่อนเริ่มแปล
4. เริ่มงานและติดตามผลจากหน้า Workspace
5. Pause/Resume หรือ Retry แถวที่เหลือเมื่อจำเป็น
6. ตรวจและแก้คำแปลด้วยมือ
7. Export เป็น UTF-8 BOM CSV

ระบบประมวลผลงานแปลทีละ job เมื่อเปิดโปรแกรมอีกครั้ง job เดิมจะทำต่อจาก checkpoint
โดยไม่ลบคำแปลที่บันทึกสำเร็จแล้ว

## ข้อมูลและ cache

ฐานข้อมูล ไฟล์งาน และ log อยู่ใน `storage/` ซึ่งไม่ถูก commit ขึ้น Git

ก่อน migration ที่เปลี่ยน schema สำคัญ ระบบจะสำรองฐานข้อมูลเดิมไว้ใน
`storage/backups/` การเปลี่ยน Glossary, Style หรือ Context Columns จะสร้าง
fingerprint ใหม่เพื่อป้องกันการนำ cache ที่ไม่ตรงกับงานกลับมาใช้

ระบบไม่เรียก Gemini แยกเพื่อวิเคราะห์ Context และจะรวมข้อความซ้ำก่อนส่งเท่าที่ทำได้
เพื่อลดจำนวน request และ token ที่ใช้ ค่าจำกัด batch และโควต้าปรับได้ใน `.env`

## สำหรับนักพัฒนา

ติดตั้ง dependencies สำหรับทดสอบ:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
cd frontend
npm.cmd install
cd ..
```

รันชุดตรวจสอบ:

```powershell
.\.venv\Scripts\python.exe -m compileall -q backend tests
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm.cmd test -- --run
npm.cmd run build
```

Tests ใช้ fake Gemini service และไม่เรียก Gemini API จริง

เมื่อเปิดโปรแกรมอยู่ ดู API documentation ได้ที่
[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## โครงสร้างโปรเจกต์

```text
backend/
  app/             FastAPI, worker, repository และ Gemini service
  app/migrations/  SQLite migrations
frontend/
  src/pages/       หน้าหลักและ Workspace
  src/components/  components ที่ใช้ร่วมกัน
  src/lib/         utilities และ Context Column helpers
  src/styles/      styles และ responsive rules
scripts/           สคริปต์สำหรับเปิดระบบบน Windows
tests/             backend และ workflow tests
docs/              เอกสารระบบ
storage/           ฐานข้อมูล ไฟล์งาน และ logs (สร้างในเครื่อง)
```

รายละเอียดพฤติกรรมของระบบอยู่ที่
[`docs/csv-translation-system-spec.md`](docs/csv-translation-system-spec.md)
