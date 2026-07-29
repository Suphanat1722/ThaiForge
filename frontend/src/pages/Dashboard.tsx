import {
  ArrowRight,
  FileText,
  Search,
  Trash2,
  UploadCloud,
} from "lucide-react";
import {
  type ChangeEvent,
  type DragEvent,
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import { api, type Job } from "../api";
import { ConfirmDialog, ErrorBanner, Spinner } from "../components/Feedback";
import { formatDate, formatNumber, statusLabel } from "../lib/format";
import { navigate } from "../lib/navigation";

type JobFilter = "all" | "active" | "review" | "completed";

function matchesFilter(job: Job, filter: JobFilter) {
  if (filter === "active") return ["running", "paused", "generating_glossary"].includes(job.status);
  if (filter === "review") return ["awaiting_review", "completed_with_errors", "failed"].includes(job.status);
  if (filter === "completed") return job.status === "completed";
  return true;
}

export default function Dashboard() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<JobFilter>("all");
  const [deleteTarget, setDeleteTarget] = useState<Job | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const loadJobs = useCallback(async () => {
    try {
      setJobs(await api<Job[]>("/api/jobs"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "โหลดประวัติงานไม่สำเร็จ");
    }
  }, []);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  const visibleJobs = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("th");
    return jobs.filter(
      (job) =>
        matchesFilter(job, filter) &&
        (!needle || job.filename.toLocaleLowerCase("th").includes(needle)),
    );
  }, [jobs, filter, query]);

  function acceptFile(candidate: File | null) {
    setError("");
    if (!candidate) return setFile(null);
    if (!candidate.name.toLowerCase().endsWith(".csv")) {
      setFile(null);
      setError("รองรับเฉพาะไฟล์ .csv เท่านั้น");
      return;
    }
    if (candidate.size > 50 * 1024 * 1024) {
      setFile(null);
      setError("ไฟล์ต้องมีขนาดไม่เกิน 50 MB");
      return;
    }
    setFile(candidate);
  }

  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    acceptFile(event.dataTransfer.files[0] ?? null);
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.append("file", file);
      const job = await api<Job>("/api/jobs/upload", { method: "POST", body });
      toast.success("ตรวจไฟล์สำเร็จ พร้อมตั้งค่าคอลัมน์");
      navigate(`/jobs/${job.id}?view=config`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "อัปโหลดไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  async function deleteJob() {
    if (!deleteTarget) return;
    setBusy(true);
    try {
      await api(`/api/jobs/${deleteTarget.id}`, { method: "DELETE" });
      toast.success(`ลบงาน “${deleteTarget.filename}” แล้ว`);
      setDeleteTarget(null);
      await loadJobs();
    } catch (err) {
      setError(err instanceof Error ? err.message : "ลบงานไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="dashboard-page">
      <section className="hero">
        <div className="hero-copy">
          <span className="eyebrow">LOCALIZATION WORKBENCH</span>
          <h1>งานแปลเกมที่ศัพท์ตรงกัน<br />และกลับมาทำต่อได้เสมอ</h1>
          <p>
            ตรวจ Glossary ก่อนเริ่ม ติดตามโควตา และเก็บทุกแถวที่แปลสำเร็จไว้ในเครื่อง
          </p>
          <div className="hero-assurance">
            <span>CSV สูงสุด 50 MB</span>
            <span>Pause / Resume</span>
            <span>เก็บผลลัพธ์บางส่วน</span>
          </div>
        </div>
        <form className="upload-panel" onSubmit={upload}>
          <div
            className={`drop-zone ${file ? "has-file" : ""} ${dragging ? "is-dragging" : ""}`}
            onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setDragging(false)}
            onDrop={drop}
            onClick={() => inputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") inputRef.current?.click();
            }}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".csv,text/csv"
              onChange={(event: ChangeEvent<HTMLInputElement>) =>
                acceptFile(event.target.files?.[0] ?? null)
              }
            />
            {file ? <FileText aria-hidden="true" /> : <UploadCloud aria-hidden="true" />}
            <strong>{file ? file.name : "ลากไฟล์ CSV มาวาง หรือคลิกเพื่อเลือก"}</strong>
            <small>
              {file
                ? `${(file.size / 1024).toFixed(1)} KB · พร้อมตรวจโครงสร้าง`
                : "UTF-8, UTF-8 BOM หรือ Windows-874"}
            </small>
          </div>
          <button className="primary-button wide" disabled={!file || busy}>
            {busy ? <Spinner label="กำลังตรวจไฟล์" /> : <>อัปโหลดและตรวจไฟล์ <ArrowRight /></>}
          </button>
        </form>
      </section>

      {error && <ErrorBanner message={error} onClose={() => setError("")} />}

      <section className="section-block">
        <div className="section-heading history-heading">
          <div>
            <span className="eyebrow">WORKSPACE</span>
            <h2>งานทั้งหมด</h2>
          </div>
          <span className="muted">{formatNumber(visibleJobs.length)} จาก {formatNumber(jobs.length)} งาน</span>
        </div>
        <div className="toolbar">
          <label className="search-field">
            <Search aria-hidden="true" />
            <span className="sr-only">ค้นหาชื่องาน</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="ค้นหาชื่อไฟล์…" />
          </label>
          <div className="segmented-control" aria-label="กรองสถานะงาน">
            {([
              ["all", "ทั้งหมด"],
              ["active", "กำลังทำ"],
              ["review", "ต้องตรวจ"],
              ["completed", "เสร็จแล้ว"],
            ] as [JobFilter, string][]).map(([value, label]) => (
              <button
                key={value}
                className={filter === value ? "active" : ""}
                aria-pressed={filter === value}
                onClick={() => setFilter(value)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {visibleJobs.length === 0 ? (
          <div className="empty-state">
            <FileText aria-hidden="true" />
            <strong>{jobs.length ? "ไม่พบงานที่ตรงกับตัวกรอง" : "ยังไม่มีงานแปล"}</strong>
            <span>{jobs.length ? "ลองเปลี่ยนคำค้นหาหรือสถานะ" : "อัปโหลด CSV ด้านบนเพื่อเริ่มงานแรก"}</span>
          </div>
        ) : (
          <div className="job-list">
            {visibleJobs.map((job) => {
              const percent = job.total_rows
                ? Math.round((job.completed_rows / job.total_rows) * 100)
                : 0;
              return (
                <article className="job-card" key={job.id}>
                  <button className="job-main" onClick={() => navigate(`/jobs/${job.id}`)}>
                    <span className={`status-dot status-${job.status}`} aria-hidden="true" />
                    <span className="job-copy">
                      <strong>{job.filename}</strong>
                      <small>{statusLabel(job.status)} · อัปเดต {formatDate(job.updated_at)}</small>
                    </span>
                    <span className="job-progress">
                      <strong>{percent}%</strong>
                      <small>{formatNumber(job.completed_rows)}/{formatNumber(job.total_rows)} แถว</small>
                    </span>
                    <ArrowRight className="arrow" aria-hidden="true" />
                  </button>
                  <button
                    className="icon-button danger-icon"
                    onClick={() => setDeleteTarget(job)}
                    disabled={["running", "generating_glossary"].includes(job.status)}
                    aria-label={`ลบงาน ${job.filename}`}
                  >
                    <Trash2 aria-hidden="true" />
                  </button>
                </article>
              );
            })}
          </div>
        )}
      </section>
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="ลบงานนี้ถาวร?"
        description={<>ไฟล์งาน “{deleteTarget?.filename}” พร้อม Glossary และผลแปลทั้งหมดจะถูกลบ การทำงานนี้ย้อนกลับไม่ได้</>}
        confirmLabel="ลบงาน"
        danger
        busy={busy}
        onConfirm={() => void deleteJob()}
      />
    </main>
  );
}

