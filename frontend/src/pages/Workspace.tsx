import {
  AlertCircle,
  ArrowLeft,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Download,
  Edit3,
  FileCheck2,
  Gauge,
  Pause,
  Play,
  Plus,
  RotateCcw,
  Search,
  Settings2,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import {
  api,
  type GlossaryEntry,
  type GlossaryRuleSettings,
  type Job,
  type Scan,
  type StyleRule,
  type TranslationRow,
  patch,
  post,
  put,
} from "../api";
import { ConfirmDialog, ErrorBanner, Spinner } from "../components/Feedback";
import { usePolling } from "../hooks/usePolling";
import {
  canOpenView,
  formatDate,
  formatNumber,
  statusLabel,
  type WorkspaceView,
  viewForStatus,
} from "../lib/format";
import {
  availableContextColumns,
  previewColumnValues,
} from "../lib/contextColumns";
import { navigate } from "../lib/navigation";

const STAGES: { value: WorkspaceView; label: string; short: string }[] = [
  { value: "config", label: "ตั้งค่าไฟล์", short: "ตั้งค่า" },
  { value: "glossary", label: "Glossary", short: "ศัพท์" },
  { value: "translate", label: "แปล", short: "แปล" },
  { value: "review", label: "ตรวจสอบและ Export", short: "ตรวจ" },
];

function setView(view: WorkspaceView) {
  const url = new URL(window.location.href);
  url.searchParams.set("view", view);
  navigate(`${url.pathname}${url.search}`);
}

function currentView(job: Job): WorkspaceView {
  const value = new URLSearchParams(window.location.search).get("view") as WorkspaceView | null;
  return value && STAGES.some((stage) => stage.value === value) && canOpenView(job, value)
    ? value
    : viewForStatus(job.status);
}

function CsvPreview({ job }: { job: Job }) {
  if (!job.preview.length) return null;
  return (
    <section className="panel preview-panel">
      <div className="panel-heading">
        <div><span className="step-number">PREVIEW</span><h2>ตัวอย่างข้อมูล</h2></div>
        <span className="badge">{job.headers.length} คอลัมน์</span>
      </div>
      <div className="table-scroll">
        <table>
          <thead><tr>{job.headers.map((header) => <th key={header}>{header}</th>)}</tr></thead>
          <tbody>
            {job.preview.slice(0, 8).map((row, index) => (
              <tr key={index}>
                {job.headers.map((header) => <td key={header} data-label={header}>{row[header] || "—"}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ConfigurationPanel({ job, onDone }: { job: Job; onDone(): Promise<void> }) {
  const [sourceColumn, setSourceColumn] = useState(job.source_column ?? job.headers[0] ?? "");
  const suggestedTarget = job.headers.find((header) => header.toLowerCase() === "translation_th")
    ?? job.headers.find((header) => /^(translation|translated|target)/i.test(header));
  const initialTarget = job.target_column ?? suggestedTarget ?? "translation_th";
  const [targetChoice, setTargetChoice] = useState(job.headers.includes(initialTarget) ? initialTarget : "__new__");
  const [newTargetColumn, setNewTargetColumn] = useState(job.headers.includes(initialTarget) ? "translation_th" : initialTarget);
  const [sourceLang, setSourceLang] = useState(job.source_lang ?? "อังกฤษ");
  const [targetLang, setTargetLang] = useState(job.target_lang ?? "ไทย");
  const [encoding, setEncoding] = useState(job.encoding);
  const [delimiter, setDelimiter] = useState(job.delimiter);
  const [contextColumns, setContextColumns] = useState<string[]>(
    job.context_columns ?? [],
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const targetColumn = targetChoice === "__new__" ? newTargetColumn.trim() : targetChoice;
  const editable = ["uploaded", "configured"].includes(job.status);
  const contextOptions = availableContextColumns(
    job.headers,
    sourceColumn,
    targetColumn,
  );
  const selectedContextColumns = contextColumns.filter((column) =>
    contextOptions.includes(column),
  );

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await put(`/api/jobs/${job.id}/configuration`, {
        source_column: sourceColumn,
        target_column: targetColumn,
        source_lang: sourceLang,
        target_lang: targetLang,
        encoding,
        delimiter,
        context_columns: selectedContextColumns,
      });
      toast.success("บันทึกโครงสร้างไฟล์แล้ว");
      await onDone();
      setView("glossary");
    } catch (err) {
      setError(err instanceof Error ? err.message : "บันทึกการตั้งค่าไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  if (!editable) {
    return (
      <div className="workspace-grid">
        <section className="panel config-summary">
          <div className="panel-heading">
            <div><span className="step-number">FILE MAPPING</span><h2>โครงสร้างที่ใช้งาน</h2></div>
            <span className="success-badge"><Check /> ตั้งค่าแล้ว</span>
          </div>
          <dl className="definition-grid">
            <div><dt>คอลัมน์ต้นฉบับ</dt><dd>{job.source_column}</dd></div>
            <div><dt>คอลัมน์ผลลัพธ์</dt><dd>{job.target_column}</dd></div>
            <div><dt>Context Columns</dt><dd>{job.context_columns.length ? job.context_columns.join(", ") : "ไม่ได้เลือก"}</dd></div>
            <div><dt>ภาษา</dt><dd>{job.source_lang} → {job.target_lang}</dd></div>
            <div><dt>รูปแบบไฟล์</dt><dd>{job.encoding} · {job.delimiter === "\t" ? "TAB" : job.delimiter}</dd></div>
          </dl>
          <p className="info-note">ล็อก mapping หลังเริ่มงานเพื่อป้องกันแถวที่แปลสำเร็จแล้วสูญหาย</p>
        </section>
        <CsvPreview job={job} />
      </div>
    );
  }

  return (
    <div className="workspace-grid config-workspace">
      <form className="panel config-panel" onSubmit={save}>
        <div className="panel-heading">
          <div><span className="step-number">01 · FILE SETUP</span><h2>ตั้งค่าไฟล์สำหรับแปล</h2></div>
          <span className="badge">{job.encoding} · {job.delimiter === "\t" ? "TAB" : job.delimiter}</span>
        </div>
        {error && <ErrorBanner message={error} onClose={() => setError("")} />}
        <div className="config-sections">
          <section className="config-section">
            <div className="config-section-heading">
              <div><span>1</span><h3>เลือกคอลัมน์คำแปล</h3></div>
              <p>เลือกข้อความต้นฉบับและตำแหน่งที่จะบันทึกผลลัพธ์</p>
            </div>
            <div className="config-fields">
              <label><span>คอลัมน์ต้นฉบับ <b>จำเป็น</b></span>
                <select value={sourceColumn} onChange={(event) => setSourceColumn(event.target.value)}>
                  {job.headers.map((header) => <option key={header}>{header}</option>)}
                </select>
              </label>
              <label><span>คอลัมน์ผลลัพธ์ <b>จำเป็น</b></span>
                <select value={targetChoice} onChange={(event) => setTargetChoice(event.target.value)}>
                  {job.headers.map((header) => <option key={header}>{header}</option>)}
                  <option value="__new__">＋ สร้างคอลัมน์ใหม่</option>
                </select>
                {targetChoice === "__new__" && (
                  <input value={newTargetColumn} onChange={(event) => setNewTargetColumn(event.target.value)} required aria-label="ชื่อคอลัมน์ใหม่" />
                )}
              </label>
            </div>
          </section>

          <section className="config-section">
            <div className="config-section-heading">
              <div><span>2</span><h3>ภาษาและรูปแบบไฟล์</h3></div>
              <p>ตรวจสอบภาษา, encoding และตัวคั่นก่อนเริ่มงาน</p>
            </div>
            <div className="config-fields">
              <label><span>ภาษาต้นทาง</span><input value={sourceLang} onChange={(event) => setSourceLang(event.target.value)} required /></label>
              <label><span>ภาษาปลายทาง</span><input value={targetLang} onChange={(event) => setTargetLang(event.target.value)} required /></label>
              <label><span>Encoding</span>
                <select value={encoding} onChange={(event) => setEncoding(event.target.value)}>
                  <option value="utf-8">UTF-8</option><option value="utf-8-sig">UTF-8 BOM</option>
                  <option value="cp874">Windows-874</option><option value="tis-620">TIS-620</option>
                </select>
              </label>
              <label><span>Delimiter</span>
                <select value={delimiter} onChange={(event) => setDelimiter(event.target.value)}>
                  <option value=",">Comma (,)</option><option value=";">Semicolon (;)</option>
                  <option value={"\t"}>Tab</option><option value="|">Pipe (|)</option>
                </select>
              </label>
            </div>
          </section>

          <fieldset className="config-section context-columns-field">
            <legend className="config-section-heading">
              <span className="config-section-title"><span>3</span><strong>ข้อมูลประกอบการแปล</strong></span>
              <span className="optional-badge">ไม่บังคับ</span>
            </legend>
            <p>เลือกข้อมูลที่ช่วยให้ AI เข้าใจผู้พูด ฉาก หรือเหตุการณ์ โดยระบบจะไม่แปลค่าเหล่านี้</p>
            {selectedContextColumns.length > 0 && (
              <div className="context-selection-summary">เลือกแล้ว {selectedContextColumns.length} คอลัมน์</div>
            )}
            <div className="context-column-options">
              {contextOptions.map((header) => {
                const values = previewColumnValues(job.preview, header);
                const checked = selectedContextColumns.includes(header);
                return (
                  <label key={header} className={checked ? "selected" : ""}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => setContextColumns((current) =>
                        current.includes(header)
                          ? current.filter((column) => column !== header)
                          : [...current, header]
                      )}
                    />
                    <span>
                      <strong>{header}</strong>
                      <small>{values.length ? `เช่น ${values.join(" · ")}` : "ไม่มีค่าตัวอย่าง"}</small>
                    </span>
                  </label>
                );
              })}
              {!contextOptions.length && <small>ไม่มีคอลัมน์อื่นที่เลือกเป็น Context ได้</small>}
            </div>
          </fieldset>
        </div>
        <div className="config-actions">
          <small>ตรวจสอบตัวอย่างข้อมูลด้านข้างก่อนยืนยัน</small>
          <button className="primary-button" disabled={busy || !targetColumn}>
            {busy ? <Spinner label="กำลังเตรียมแถว" /> : <>ยืนยันโครงสร้าง <ChevronRight /></>}
          </button>
        </div>
      </form>
      <CsvPreview job={job} />
    </div>
  );
}

function GlossaryRow({
  jobId,
  entry,
  onChanged,
}: {
  jobId: string;
  entry: GlossaryEntry;
  onChanged(): Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [source, setSource] = useState(entry.source_term);
  const [target, setTarget] = useState(entry.target_term);
  const [note, setNote] = useState(entry.rule_note);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const dirty = source !== entry.source_term || target !== entry.target_term || note !== entry.rule_note;

  function cancel() {
    setSource(entry.source_term);
    setTarget(entry.target_term);
    setNote(entry.rule_note);
    setEditing(false);
  }
  async function save() {
    setBusy(true);
    try {
      await patch(`/api/jobs/${jobId}/glossary/${entry.id}`, {
        source_term: source, target_term: target, rule_note: note,
      });
      toast.success("บันทึกคำศัพท์แล้ว");
      setEditing(false);
      await onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "บันทึกคำศัพท์ไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }
  async function toggle() {
    setBusy(true);
    try {
      await patch(`/api/jobs/${jobId}/glossary/${entry.id}`, { is_active: !entry.is_active });
      await onChanged();
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    setBusy(true);
    try {
      await api(`/api/jobs/${jobId}/glossary/${entry.id}`, { method: "DELETE" });
      toast.success("ลบคำศัพท์แล้ว");
      setConfirmDelete(false);
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <tr className={!entry.is_active ? "inactive-row" : ""}>
        <td data-label="ต้นฉบับ">
          {editing ? <input aria-label={`คำต้นฉบับ ${entry.source_term}`} value={source} onChange={(event) => setSource(event.target.value)} /> : <strong>{entry.source_term}</strong>}
        </td>
        <td data-label="คำแปลบังคับ">
          {editing ? <input aria-label={`คำแปลของ ${entry.source_term}`} value={target} onChange={(event) => setTarget(event.target.value)} /> : entry.target_term}
        </td>
        <td data-label="วิธี"><span className="origin-badge">{({
          translate: "แปลไทย",
          transliterate: "ทับศัพท์",
          keep: "คงอังกฤษ",
          mixed: "ผสม",
        } as const)[entry.translation_mode] ?? "ผสม"}</span></td>
        <td data-label="หมายเหตุ">
          {editing ? <input aria-label={`หมายเหตุของ ${entry.source_term}`} value={note} onChange={(event) => setNote(event.target.value)} placeholder="บริบทหรือข้อกำหนด" /> : (entry.rule_note || "—")}
        </td>
        <td data-label="แหล่งที่มา"><span className="origin-badge">{entry.created_by === "ai" ? "AI" : "ผู้ใช้"}</span></td>
        <td className="row-actions">
          {editing ? (
            <>
              <button className="icon-button positive" onClick={() => void save()} disabled={busy || !dirty || !source.trim() || !target.trim()} aria-label="บันทึก"><Check /></button>
              <button className="icon-button" onClick={cancel} disabled={busy} aria-label="ยกเลิก"><X /></button>
            </>
          ) : (
            <>
              <button className="icon-button" onClick={() => setEditing(true)} disabled={busy} aria-label={`แก้ไข ${entry.source_term}`}><Edit3 /></button>
              <button className="text-button" onClick={() => void toggle()} disabled={busy}>{entry.is_active ? "ปิด" : "เปิด"}</button>
              <button className="icon-button danger-icon" onClick={() => setConfirmDelete(true)} disabled={busy} aria-label={`ลบ ${entry.source_term}`}><Trash2 /></button>
            </>
          )}
        </td>
      </tr>
      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="ลบคำศัพท์นี้?"
        description={<>คำ “{entry.source_term}” จะไม่ถูกส่งให้ AI ใน batch ถัดไป แต่ประวัติ revision จะยังอยู่เพื่อการสแกนผลกระทบ</>}
        confirmLabel="ลบคำศัพท์"
        danger
        busy={busy}
        onConfirm={() => void remove()}
      />
    </>
  );
}

function GlossaryRulesEditor({
  job,
  onChanged,
  onDirtyChange,
}: {
  job: Job;
  onChanged(): Promise<void>;
  onDirtyChange?(dirty: boolean): void;
}) {
  const [rulesText, setRulesText] = useState("");
  const [savedText, setSavedText] = useState("");
  const [settings, setSettings] = useState<GlossaryRuleSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const editable = ["configured", "awaiting_review"].includes(job.status);
  const dirty = rulesText !== savedText;
  const rules = rulesText.split("\n").map((rule) => rule.trim()).filter(Boolean);
  const totalChars = rules.reduce((total, rule) => total + rule.length, 0);
  const invalid = rules.length > 20
    || rules.some((rule) => rule.length > 300) || totalChars > 4000;

  const load = useCallback(async () => {
    const detail = await api<Job>(`/api/jobs/${job.id}`);
    const next = detail.glossary_rule_settings;
    if (next) {
      const text = next.rules.join("\n");
      setSettings(next);
      setRulesText(text);
      setSavedText(text);
    }
  }, [job.id]);

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, [load, job.glossary_rules_revision, job.glossary_rules_applied_revision]);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  async function saveRules() {
    setBusy(true); setError("");
    try {
      const next = await put<GlossaryRuleSettings>(`/api/jobs/${job.id}/glossary-rules`, {
        rules,
      });
      setSettings(next);
      setSavedText(next.rules.join("\n"));
      setRulesText(next.rules.join("\n"));
      toast.success("บันทึกกฎสร้าง Glossary แล้ว");
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "บันทึกกฎไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel glossary-rules-editor">
      <div><span className="step-number">PROJECT OVERRIDES</span><h2>ข้อกำหนดเฉพาะโปรเจกต์</h2></div>
      <p className="panel-description">ไม่บังคับ — ใช้เฉพาะธรรมเนียมของเกมนี้ ระบบมีหลักแปล/ทับศัพท์/คงอังกฤษ/ผสมให้อยู่แล้ว</p>
      {error && <ErrorBanner message={error} onClose={() => setError("")} />}
      <textarea
        rows={10}
        value={rulesText}
        onChange={(event) => setRulesText(event.target.value)}
        disabled={!editable || busy}
        aria-label="ข้อกำหนดเฉพาะโปรเจกต์"
        placeholder={"ตัวอย่าง: ใช้การสะกดชื่อตัวละครตามภาคก่อน\nเว้นว่างได้หากไม่มีข้อกำหนดเฉพาะ"}
      />
      <small className={invalid ? "field-error" : "muted"}>
        {rules.length}/20 กฎ · {totalChars}/4,000 ตัวอักษร
      </small>
      {settings?.needs_regeneration && (
        <div className="dirty-note" role="status">กฎเปลี่ยนหลังสร้าง Glossary ต้องสร้างใหม่จึงจะมีผล</div>
      )}
      {dirty && <div className="dirty-note" role="status">มีการแก้ไขที่ยังไม่บันทึก</div>}
      {editable ? (
        <div className="rule-actions">
          <button className="primary-button wide" onClick={() => void saveRules()} disabled={busy || !dirty || invalid}>บันทึกข้อกำหนด</button>
          <button className="text-button wide" onClick={() => setRulesText("")} disabled={busy || !rulesText}>ล้างข้อความ</button>
        </div>
      ) : (
        <div className="info-note">งานเริ่มแปลแล้ว กฎชุดนี้เปิดให้อ่านอย่างเดียว</div>
      )}
    </section>
  );
}

function GlossaryPanel({
  job,
  onJobChanged,
  onGenerate,
}: {
  job: Job;
  onJobChanged(): Promise<void>;
  onGenerate(): Promise<void>;
}) {
  const [entries, setEntries] = useState<GlossaryEntry[]>([]);
  const [rules, setRules] = useState<StyleRule[]>([]);
  const [styleText, setStyleText] = useState("");
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [state, setState] = useState("");
  const [origin, setOrigin] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [newSource, setNewSource] = useState("");
  const [newTarget, setNewTarget] = useState("");
  const [newNote, setNewNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmGenerate, setConfirmGenerate] = useState(false);
  const [glossaryRulesDirty, setGlossaryRulesDirty] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  const load = useCallback(async () => {
    const params = new URLSearchParams({ page: String(page), page_size: "50" });
    if (debouncedQuery) params.set("q", debouncedQuery);
    if (state) params.set("state", state);
    if (origin) params.set("origin", origin);
    const data = await api<{
      entries: GlossaryEntry[];
      style_rules: StyleRule[];
      total: number;
    }>(`/api/jobs/${job.id}/glossary?${params}`);
    setEntries(data.entries);
    setRules(data.style_rules);
    setTotal(data.total);
    setStyleText((current) => current || data.style_rules.map((rule) => rule.rule_text).join("\n"));
  }, [job.id, page, debouncedQuery, state, origin]);

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, [load, job.glossary_revision, job.style_revision]);

  async function changed() {
    await Promise.all([load(), onJobChanged()]);
  }
  async function addEntry(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await post(`/api/jobs/${job.id}/glossary`, { source_term: newSource, target_term: newTarget, rule_note: newNote });
      setNewSource(""); setNewTarget(""); setNewNote("");
      toast.success("เพิ่มคำศัพท์แล้ว");
      await changed();
    } catch (err) {
      setError(err instanceof Error ? err.message : "เพิ่มคำไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }
  async function saveStyles() {
    setBusy(true);
    try {
      await put(`/api/jobs/${job.id}/style-rules`, { rules: styleText.split("\n").filter((rule) => rule.trim()) });
      toast.success("บันทึกกฎสไตล์แล้ว");
      await changed();
    } catch (err) {
      setError(err instanceof Error ? err.message : "บันทึกกฎไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }
  async function useDefaults() {
    setBusy(true);
    try {
      const data = await post<{ style_rules: StyleRule[] }>(`/api/jobs/${job.id}/style-rules/use-defaults`);
      setStyleText(data.style_rules.map((rule) => rule.rule_text).join("\n"));
      await changed();
      toast.success("ใช้กฎแนะนำแล้ว");
    } finally {
      setBusy(false);
    }
  }
  const savedStyle = rules.map((rule) => rule.rule_text).join("\n");

  if (job.status === "configured") {
    return (
      <div className="glossary-setup">
        <GlossaryRulesEditor job={job} onChanged={onJobChanged} onDirtyChange={setGlossaryRulesDirty} />
        <section className="center-stage panel">
          <span className="stage-icon"><Sparkles /></span>
          <span className="step-number">02 · GLOSSARY</span>
          <h2>สร้างคลังศัพท์ชุดแรกจากทั้งไฟล์</h2>
          <p>Gemini จะวิเคราะห์เป็น batch ตามกฎที่บันทึกไว้ คำแปลเดิมยังไม่ถูกแก้ไขในขั้นตอนนี้</p>
          {glossaryRulesDirty && <div className="dirty-note">กรุณาบันทึกกฎก่อนเริ่มสร้าง Glossary</div>}
          <button className="primary-button" disabled={busy || glossaryRulesDirty} onClick={() => void onGenerate()}>
            <Sparkles /> เริ่มวิเคราะห์คำศัพท์
          </button>
        </section>
      </div>
    );
  }
  if (job.status === "generating_glossary") {
    const percent = job.glossary_chunks_total
      ? Math.round(job.glossary_chunks_completed / job.glossary_chunks_total * 100)
      : 0;
    return (
      <section className="center-stage panel">
        <Spinner label="Gemini กำลังวิเคราะห์คำศัพท์" />
        <h2>อ่านศัพท์จากทุกส่วนของไฟล์</h2>
        <p>ปิดหน้านี้ได้ worker จะทำงานต่อในเครื่อง</p>
        <div className="generation-status">
          <span>ชุดที่ {job.glossary_chunks_completed} จาก {job.glossary_chunks_total || "—"}</span>
          <strong>{percent}%</strong>
        </div>
        <div className="progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
          <span style={{ width: `${percent}%` }} />
        </div>
      </section>
    );
  }

  return (
    <div className="glossary-layout">
      <section className="panel glossary-panel">
        <div className="panel-heading">
          <div><span className="step-number">GLOSSARY · REV {job.glossary_revision}</span><h2>คำศัพท์บังคับ</h2></div>
          <div className="panel-actions">
            <span className="badge">{formatNumber(total)} คำ</span>
            {job.status === "awaiting_review" && (
              <button className="secondary-button" onClick={() => setConfirmGenerate(true)}><RotateCcw /> สร้างใหม่</button>
            )}
          </div>
        </div>
        <p className="panel-description">แก้คำได้ระหว่างแปล โดย revision ใหม่จะมีผลเฉพาะ batch ถัดไป</p>
        {error && <ErrorBanner message={error} onClose={() => setError("")} />}
        <div className="toolbar compact-toolbar">
          <label className="search-field">
            <Search /><span className="sr-only">ค้นหา Glossary</span>
            <input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder="ค้นหาคำหรือหมายเหตุ…" />
          </label>
          <select value={state} onChange={(event) => { setState(event.target.value); setPage(1); }} aria-label="กรองสถานะคำ">
            <option value="">ทุกสถานะ</option><option value="active">ใช้งาน</option><option value="inactive">ปิดไว้</option>
          </select>
          <select value={origin} onChange={(event) => { setOrigin(event.target.value); setPage(1); }} aria-label="กรองแหล่งคำ">
            <option value="">ทุกแหล่ง</option><option value="ai">AI</option><option value="user">ผู้ใช้</option>
          </select>
        </div>
        <div className="table-scroll glossary-table">
          <table>
            <thead><tr><th>ต้นฉบับ</th><th>คำแปลบังคับ</th><th>วิธี</th><th>หมายเหตุ</th><th>ที่มา</th><th>จัดการ</th></tr></thead>
            <tbody>
              {entries.map((entry) => <GlossaryRow key={entry.id} jobId={job.id} entry={entry} onChanged={changed} />)}
            </tbody>
          </table>
          {!entries.length && <div className="empty-state compact"><strong>ไม่พบคำศัพท์</strong><span>ลองเปลี่ยนตัวกรองหรือเพิ่มคำใหม่</span></div>}
        </div>
        <form className="inline-add" onSubmit={addEntry}>
          <input aria-label="คำต้นฉบับใหม่" placeholder="คำต้นฉบับ" value={newSource} onChange={(event) => setNewSource(event.target.value)} required />
          <input aria-label="คำแปลใหม่" placeholder="คำแปล" value={newTarget} onChange={(event) => setNewTarget(event.target.value)} required />
          <input aria-label="หมายเหตุคำใหม่" placeholder="หมายเหตุ (ไม่บังคับ)" value={newNote} onChange={(event) => setNewNote(event.target.value)} />
          <button className="small-button" disabled={busy}><Plus /> เพิ่มคำ</button>
        </form>
        <Pagination page={page} pageSize={50} total={total} onPage={setPage} />
      </section>
      <div className="rules-sidebar">
        <GlossaryRulesEditor job={job} onChanged={onJobChanged} onDirtyChange={setGlossaryRulesDirty} />
        <aside className="panel style-editor">
          <div><span className="step-number">STYLE RULES</span><h2>กฎสไตล์</h2></div>
          <p className="panel-description">ใช้ควบคุมสำนวนของการแปลประโยค หนึ่งกฎต่อบรรทัด</p>
          <textarea rows={12} value={styleText} onChange={(event) => setStyleText(event.target.value)} aria-label="กฎสไตล์" />
          {styleText !== savedStyle && <div className="dirty-note" role="status">มีการแก้ไขที่ยังไม่บันทึก</div>}
          <button className="primary-button wide" onClick={() => void saveStyles()} disabled={busy || styleText === savedStyle}>บันทึกกฎ</button>
          <button className="text-button wide" onClick={() => void useDefaults()} disabled={busy}>ใช้กฎแนะนำแบบสั้น</button>
        </aside>
      </div>
      <ConfirmDialog
        open={confirmGenerate}
        onOpenChange={setConfirmGenerate}
        title="สร้าง Glossary ใหม่?"
        description="ระบบจะวิเคราะห์ข้อความทั้งไฟล์อีกครั้ง และแทนที่ Glossary ปัจจุบันเมื่อวิเคราะห์สำเร็จ คำแปลที่สำเร็จแล้วจะไม่ถูกลบ"
        confirmLabel="เริ่มสร้างใหม่"
        busy={busy}
        onConfirm={() => { if (!glossaryRulesDirty) { setConfirmGenerate(false); void onGenerate(); } }}
      />
    </div>
  );
}

function ProgressPanel({ job }: { job: Job }) {
  const counts = job.counts;
  const percent = job.total_rows ? Math.round(job.completed_rows / job.total_rows * 100) : 0;
  const quota = job.quota_usage;
  const quotaPercent = quota?.budget ? Math.min(100, Math.round(quota.used / quota.budget * 100)) : 0;
  return (
    <div className="progress-dashboard">
      <section className="panel progress-panel">
        <div className="progress-top">
          <div><span className="eyebrow">JOB PROGRESS</span><strong className="big-number">{percent}%</strong></div>
          <span className={`status-badge status-${job.status}`}>{statusLabel(job.status)}</span>
        </div>
        <div className="progress-track" role="progressbar" aria-label={`แปลเสร็จ ${percent}%`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
          <span style={{ width: `${percent}%` }} />
        </div>
        <div className="metric-grid">
          <div><small>สำเร็จ</small><strong>{formatNumber(counts?.done ?? 0)}</strong></div>
          <div><small>รอแปล</small><strong>{formatNumber(counts?.pending ?? 0)}</strong></div>
          <div><small>ล้มเหลว</small><strong>{formatNumber(counts?.failed ?? 0)}</strong></div>
          <div><small>รอแปลใหม่</small><strong>{formatNumber(counts?.retranslation_pending ?? 0)}</strong></div>
        </div>
      </section>
      <section className="panel quota-card">
        <div className="card-label"><Gauge /><span>โควตาวันนี้</span></div>
        <strong>{formatNumber(quota?.used ?? 0)} <small>/ {formatNumber(quota?.budget ?? 0)} requests</small></strong>
        <div className="progress-track quota-track" role="progressbar" aria-label="โควตาที่ใช้" aria-valuemin={0} aria-valuemax={100} aria-valuenow={quotaPercent}>
          <span style={{ width: `${quotaPercent}%` }} />
        </div>
        <small>รีเซ็ต {quota ? formatDate(quota.reset_at) : "—"}</small>
      </section>
      <section className="panel efficiency-card">
        <div className="card-label"><Sparkles /><span>ประสิทธิภาพ</span></div>
        <strong>{job.quota_efficiency?.average_rows_per_request ?? 0} <small>แถว / request</small></strong>
        <div className="efficiency-grid">
          <span>Cache <b>{formatNumber(job.quota_efficiency?.cache_hits ?? 0)}</b></span>
          <span>ประหยัด <b>{formatNumber(job.quota_efficiency?.requests_saved ?? 0)}</b></span>
        </div>
      </section>
      {job.pause_reason === "quota" && job.quota_resume_at && (
        <div className="quota-banner" role="status">
          โควตารายวันเต็ม แถวที่เหลือยังอยู่ในคิว และจะเริ่มต่อประมาณ {formatDate(job.quota_resume_at)}
        </div>
      )}
    </div>
  );
}

function Pagination({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage(value: number): void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <nav className="pagination" aria-label="เปลี่ยนหน้า">
      <button className="text-button" disabled={page === 1} onClick={() => onPage(page - 1)}><ChevronLeft /> ก่อนหน้า</button>
      <span>หน้า {page} จาก {totalPages} · {formatNumber(total)} รายการ</span>
      <button className="text-button" disabled={page >= totalPages} onClick={() => onPage(page + 1)}>ถัดไป <ChevronRight /></button>
    </nav>
  );
}

function RowsPanel({
  job,
  onChanged,
  editable = false,
}: {
  job: Job;
  onChanged(): Promise<void>;
  editable?: boolean;
}) {
  const [rows, setRows] = useState<TranslationRow[]>([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState("");
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [editingRowId, setEditingRowId] = useState<string | null>(null);
  const [draftTranslation, setDraftTranslation] = useState("");
  const [savingRowId, setSavingRowId] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  const load = useCallback(async () => {
    const params = new URLSearchParams({ page: String(page), page_size: "50" });
    if (filter) params.set("status", filter);
    if (debouncedQuery) params.set("q", debouncedQuery);
    const data = await api<{ items: TranslationRow[]; total: number }>(`/api/jobs/${job.id}/rows?${params}`);
    setRows(data.items); setTotal(data.total);
  }, [job.id, page, filter, debouncedQuery]);

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, [load, job.updated_at]);

  async function retry(rowId: string) {
    try {
      await post(`/api/jobs/${job.id}/rows/${rowId}/retry`);
      toast.success("นำแถวกลับเข้าคิวแล้ว");
      await Promise.all([load(), onChanged()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "นำแถวกลับเข้าคิวไม่สำเร็จ");
    }
  }

  function beginEdit(row: TranslationRow) {
    setEditingRowId(row.id);
    setDraftTranslation(row.translated_text ?? "");
    setError("");
  }

  function cancelEdit() {
    setEditingRowId(null);
    setDraftTranslation("");
  }

  async function saveEdit(rowId: string) {
    setSavingRowId(rowId);
    setError("");
    try {
      await patch(`/api/jobs/${job.id}/rows/${rowId}`, {
        translated_text: draftTranslation,
      });
      setEditingRowId(null);
      setDraftTranslation("");
      toast.success("บันทึกคำแปลที่แก้ไขแล้ว");
      await Promise.all([load(), onChanged()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "บันทึกคำแปลไม่สำเร็จ");
    } finally {
      setSavingRowId(null);
    }
  }

  return (
    <section className="panel rows-panel">
      <div className="panel-heading">
        <div><span className="step-number">TRANSLATION ROWS</span><h2>รายละเอียดรายแถว</h2></div>
        <span className="badge">{formatNumber(total)} แถว</span>
      </div>
      <div className="toolbar compact-toolbar">
        <label className="search-field"><Search /><span className="sr-only">ค้นหาข้อความ</span>
          <input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder="ค้นหาต้นฉบับหรือคำแปล…" />
        </label>
        <select value={filter} onChange={(event) => { setFilter(event.target.value); setPage(1); }} aria-label="กรองสถานะแถว">
          <option value="">ทุกสถานะ</option><option value="done">สำเร็จ</option><option value="pending">รอแปล</option>
          <option value="failed">ล้มเหลว</option><option value="skipped">ข้าม</option>
        </select>
      </div>
      {error && <ErrorBanner message={error} onClose={() => setError("")} />}
      <div className="table-scroll rows-table">
        <table>
          <thead><tr><th>#</th><th>ต้นฉบับ</th><th>ผลลัพธ์</th><th>สถานะ</th><th>จัดการ</th></tr></thead>
          <tbody>
            {rows.map((row) => {
              const isExpanded = expanded.has(row.id);
              const isEditing = editingRowId === row.id;
              const isSaving = savingRowId === row.id;
              return (
                <tr key={row.id} className={isEditing ? "editing-row" : ""}>
                  <td data-label="#" className="row-number">{row.row_index + 1}</td>
                  <td data-label="ต้นฉบับ" className="text-cell" title={row.source_text}>
                    {row.source_text || "—"}
                    {Object.keys(row.context).length > 0 && (
                      <dl className="row-context">
                        {Object.entries(row.context).map(([name, value]) => (
                          <div key={name}><dt>{name}</dt><dd>{value}</dd></div>
                        ))}
                      </dl>
                    )}
                  </td>
                  <td data-label="ผลลัพธ์" className="text-cell" title={isEditing ? undefined : row.translated_text ?? row.original_target}>
                    {isEditing ? (
                      <div className="translation-editor">
                        <textarea
                          value={draftTranslation}
                          onChange={(event) => setDraftTranslation(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Escape") cancelEdit();
                            if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                              event.preventDefault();
                              void saveEdit(row.id);
                            }
                          }}
                          rows={5}
                          autoFocus
                          aria-label={`แก้คำแปลแถว ${row.row_index + 1}`}
                        />
                        <small>รักษา protected tokens และ control codes ให้ครบ · Ctrl+Enter เพื่อบันทึก</small>
                      </div>
                    ) : (
                      (row.translated_text ?? row.original_target) || "—"
                    )}
                    {row.last_error && isExpanded && <small className="row-error">{row.last_error}</small>}
                  </td>
                  <td data-label="สถานะ"><span className={`mini-status mini-${row.status}`}>{statusLabel(row.status)}</span></td>
                  <td className="row-actions">
                    {isEditing ? (
                      <>
                        <button className="small-button" disabled={isSaving} onClick={() => void saveEdit(row.id)}>
                          {isSaving ? <Spinner /> : <><Check /> บันทึก</>}
                        </button>
                        <button className="text-button" disabled={isSaving} onClick={cancelEdit}><X /> ยกเลิก</button>
                      </>
                    ) : (
                      editable && row.status === "done" && row.translated_text !== null
                        ? <button className="text-button edit-translation-button" onClick={() => beginEdit(row)}><Edit3 /> แก้คำแปล</button>
                        : null
                    )}
                    {!isEditing && row.last_error && <button className="icon-button" aria-label="ดูข้อผิดพลาด" aria-expanded={isExpanded} onClick={() => setExpanded((current) => {
                      const next = new Set(current); isExpanded ? next.delete(row.id) : next.add(row.id); return next;
                    })}><ChevronDown className={isExpanded ? "rotated" : ""} /></button>}
                    {!isEditing && row.status === "failed" && Boolean(row.retryable) && <button className="text-button" onClick={() => void retry(row.id)}>Retry</button>}
                    {!isEditing && row.status === "failed" && !row.retryable && <small className="permanent-label">ข้อผิดพลาดถาวร</small>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!rows.length && <div className="empty-state compact"><strong>ไม่พบแถวที่ตรงกับตัวกรอง</strong></div>}
      </div>
      <Pagination page={page} pageSize={50} total={total} onPage={setPage} />
    </section>
  );
}

function ScanPanel({ job, onChanged }: { job: Job; onChanged(): Promise<void> }) {
  const [scan, setScan] = useState<Scan | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function runScan() {
    setBusy(true); setError("");
    try {
      const result = await post<Scan>(`/api/jobs/${job.id}/retranslation-scans`);
      setScan(result); setSelected(new Set(result.items.map((item) => item.row_id)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "สแกนไม่สำเร็จ");
    } finally { setBusy(false); }
  }
  async function confirm(all: boolean) {
    if (!scan) return;
    setBusy(true);
    try {
      const result = await post<{ queued: number }>(`/api/jobs/${job.id}/retranslation-scans/${scan.id}/confirm`, { row_ids: all ? null : [...selected] });
      toast.success(`นำเข้าคิวแล้ว ${formatNumber(result.queued)} แถว`);
      setScan({ ...scan, status: "confirmed" });
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "ยืนยันผลสแกนไม่สำเร็จ");
    } finally { setBusy(false); }
  }
  return (
    <section className="panel scan-panel">
      <div className="panel-heading">
        <div><span className="step-number">LOCAL SCAN · 0 QUOTA</span><h2>หาคำแปลที่ได้รับผลกระทบ</h2></div>
        <button className="secondary-button" disabled={busy} onClick={() => void runScan()}>
          {busy ? <Spinner label="กำลังสแกน" /> : <><Search /> สแกนในเครื่อง</>}
        </button>
      </div>
      <p className="panel-description">ตรวจจาก Source และประวัติ Glossary ในฐานข้อมูล ไม่เรียก AI</p>
      {error && <ErrorBanner message={error} onClose={() => setError("")} />}
      {scan && (
        <div className="scan-results">
          <div className="scan-summary"><strong>พบ {formatNumber(scan.candidate_count)} แถว</strong><span>Glossary revision {scan.glossary_revision}</span></div>
          {!scan.items.length ? <div className="empty-state compact"><Check /><strong>ไม่มีแถวที่ต้องแปลใหม่</strong></div> : (
            <>
              <div className="scan-items">
                {scan.items.map((item) => (
                  <label className="scan-item" key={item.row_id}>
                    <input type="checkbox" checked={selected.has(item.row_id)} disabled={scan.status !== "ready"} onChange={() => setSelected((current) => {
                      const next = new Set(current); next.has(item.row_id) ? next.delete(item.row_id) : next.add(item.row_id); return next;
                    })} />
                    <span><strong>แถว {item.row_index + 1}: {item.source_text}</strong><small>{item.reasons.map((reason) => `${reason.source_term} — ${reason.reason}`).join(" · ")}</small></span>
                  </label>
                ))}
              </div>
              {scan.status === "ready" && <div className="scan-actions">
                <button className="primary-button" disabled={!selected.size || busy} onClick={() => void confirm(false)}>ยืนยัน {selected.size} แถวที่เลือก</button>
                {scan.candidate_count > scan.items.length && <button className="text-button" onClick={() => void confirm(true)}>ยืนยันทั้งหมด {formatNumber(scan.candidate_count)} แถว</button>}
              </div>}
            </>
          )}
        </div>
      )}
    </section>
  );
}

function TranslationView({
  job,
  onChanged,
  action,
  busyAction,
}: {
  job: Job;
  onChanged(): Promise<void>;
  action(name: string, path: string, body?: unknown): Promise<void>;
  busyAction: string;
}) {
  const hasRetry = Boolean(job.counts && (job.counts.retryable_failed || job.counts.retranslation_retryable_failed));
  return (
    <div className="workspace-stack">
      <ProgressPanel job={job} />
      {(job.counts?.failed ?? 0) > 0 && (
        <section className="control-strip">
          <div><AlertCircle /><span><strong>แถวที่ต้องตรวจ</strong><small>Retry เฉพาะข้อผิดพลาดชั่วคราว แถวสำเร็จจะไม่ถูกแตะ</small></span></div>
          <div>
            {hasRetry && <button className="secondary-button" disabled={Boolean(busyAction)} onClick={() => void action("retry", `/api/jobs/${job.id}/retry-failed`, { resume: true })}><RotateCcw /> Retry และแปลต่อ</button>}
            <a className="text-button" href={`/api/jobs/${job.id}/errors/export`}><Download /> Error report</a>
          </div>
        </section>
      )}
      <RowsPanel job={job} onChanged={onChanged} />
    </div>
  );
}

function ReviewView({ job, onChanged }: { job: Job; onChanged(): Promise<void> }) {
  return (
    <div className="workspace-stack">
      <section className="review-hero panel">
        <span className="stage-icon"><FileCheck2 /></span>
        <div>
          <span className="step-number">04 · REVIEW & EXPORT</span>
          <h2>{job.status === "completed" ? "งานแปลพร้อม Export" : "ตรวจผลลัพธ์ก่อน Export"}</h2>
          <p>ผลแปลที่สำเร็จทั้งหมดอยู่ในฐานข้อมูลแล้ว Export จะเขียนลงคอลัมน์ {job.target_column}</p>
        </div>
        <a className="primary-button" href={`/api/jobs/${job.id}/export`}><Download /> Export CSV</a>
      </section>
      <ProgressPanel job={job} />
      <ScanPanel job={job} onChanged={onChanged} />
      <RowsPanel job={job} onChanged={onChanged} editable />
    </div>
  );
}

export default function Workspace({ jobId }: { jobId: string }) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [dismissedJobError, setDismissedJobError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [density, setDensity] = useState<"comfortable" | "compact">(() =>
    window.localStorage.getItem("thaiforge-density") === "compact"
      ? "compact"
      : "comfortable",
  );
  const loadVersion = useRef(0);

  const load = useCallback(async (signal?: AbortSignal) => {
    const version = ++loadVersion.current;
    try {
      const next = await api<Job>(`/api/jobs/${jobId}`, { signal });
      if (version !== loadVersion.current) return;
      setJob(next);
      setLastUpdated(new Date());
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof Error ? err.message : "โหลดงานไม่สำเร็จ");
    }
  }, [jobId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const pollDelay = job && ["running", "generating_glossary"].includes(job.status) ? 2000 : 5000;
  usePolling(async (signal) => load(signal), pollDelay, Boolean(job));

  async function action(name: string, path: string, body?: unknown) {
    setBusyAction(name); setError("");
    try {
      await post(path, body);
      await load();
      const messages: Record<string, string> = {
        start: "เริ่มแปลแล้ว", pause: "หยุดงานชั่วคราวแล้ว",
        resume: "เริ่มแปลต่อจากแถวที่เหลือแล้ว", retry: "นำข้อผิดพลาดชั่วคราวกลับเข้าคิวแล้ว",
        glossary: "เริ่มสร้าง Glossary แล้ว",
      };
      if (messages[name]) toast.success(messages[name]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ทำรายการไม่สำเร็จ");
    } finally { setBusyAction(""); }
  }

  if (!job) return <main className="loading-page"><div className="loading-skeleton" /><Spinner label="กำลังเปิดงาน" /></main>;
  const view = currentView(job);
  const canExport = Boolean(job.target_column);
  function toggleDensity() {
    const next = density === "comfortable" ? "compact" : "comfortable";
    setDensity(next);
    window.localStorage.setItem("thaiforge-density", next);
  }

  const primaryAction = job.status === "awaiting_review"
    ? <button className="primary-button" disabled={Boolean(busyAction)} onClick={() => void action("start", `/api/jobs/${job.id}/start`)}>{busyAction === "start" ? <Spinner /> : <><Play /> ยืนยันและเริ่มแปล</>}</button>
    : job.status === "running"
      ? <button className="secondary-button" disabled={Boolean(busyAction)} onClick={() => void action("pause", `/api/jobs/${job.id}/pause`)}><Pause /> หยุดชั่วคราว</button>
      : job.status === "paused"
        ? <button className="primary-button" disabled={Boolean(busyAction)} onClick={() => void action("resume", `/api/jobs/${job.id}/resume`)}><Play /> แปลต่อ</button>
        : canExport
          ? <a className="primary-button" href={`/api/jobs/${job.id}/export`}><Download /> Export CSV</a>
          : null;

  return (
    <main className={`workspace-page density-${density}`}>
      <header className="workspace-header">
        <button className="back-button" onClick={() => navigate("/")}><ArrowLeft /> งานทั้งหมด</button>
        <div className="file-title">
          <span className={`status-dot status-${job.status}`} aria-hidden="true" />
          <div><h1>{job.filename}</h1><small>{job.source_lang && job.target_lang ? `${job.source_lang} → ${job.target_lang} · ` : ""}{statusLabel(job.status)} · อัปเดต {lastUpdated ? formatDate(lastUpdated.toISOString()) : "—"}</small></div>
        </div>
        <div className="header-actions">
          <button
            className="icon-button density-toggle"
            onClick={toggleDensity}
            aria-label={density === "comfortable" ? "ใช้มุมมองแบบกระชับ" : "ใช้มุมมองแบบสบายตา"}
            title={density === "comfortable" ? "มุมมองแบบกระชับ" : "มุมมองแบบสบายตา"}
          >
            <Settings2 />
          </button>
          {primaryAction}
        </div>
      </header>
      <nav className="stage-nav" aria-label="ขั้นตอนงาน">
        {STAGES.map((stage, index) => {
          const enabled = canOpenView(job, stage.value);
          const active = view === stage.value;
          return (
            <button key={stage.value} disabled={!enabled} className={active ? "active" : ""} aria-current={active ? "step" : undefined} onClick={() => setView(stage.value)}>
              <span>{!active && enabled && viewForStatus(job.status) !== stage.value ? <Check /> : index + 1}</span>
              <b>{stage.label}</b><small>{stage.short}</small>
            </button>
          );
        })}
      </nav>

      <div className="workspace-content">
        {error && <ErrorBanner message={error} onClose={() => setError("")} />}
        {job.last_error && dismissedJobError !== job.last_error && (
          <ErrorBanner message={job.last_error} onClose={() => setDismissedJobError(job.last_error)} />
        )}
        {view === "config" && <ConfigurationPanel job={job} onDone={() => load()} />}
        {view === "glossary" && <GlossaryPanel job={job} onJobChanged={() => load()} onGenerate={() => action("glossary", `/api/jobs/${job.id}/glossary/generate`)} />}
        {view === "translate" && <TranslationView job={job} onChanged={() => load()} action={action} busyAction={busyAction} />}
        {view === "review" && <ReviewView job={job} onChanged={() => load()} />}
      </div>
      <div className="mobile-action-bar">{primaryAction}</div>
    </main>
  );
}
