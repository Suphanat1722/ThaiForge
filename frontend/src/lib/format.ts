import type { Job } from "../api";

export const STATUS_LABELS: Record<string, string> = {
  uploaded: "รอตั้งค่าไฟล์",
  configured: "พร้อมสร้าง Glossary",
  generating_glossary: "กำลังสร้าง Glossary",
  awaiting_review: "รอตรวจ Glossary",
  running: "กำลังแปล",
  paused: "หยุดชั่วคราว",
  completed: "เสร็จสมบูรณ์",
  completed_with_errors: "เสร็จพร้อมข้อผิดพลาด",
  failed: "งานล้มเหลว",
  pending: "รอแปล",
  in_progress: "กำลังแปล",
  done: "สำเร็จ",
  skipped: "ข้าม",
};

export function formatDate(value: string) {
  return new Intl.DateTimeFormat("th-TH", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat("th-TH").format(value);
}

export function statusLabel(status: string) {
  return STATUS_LABELS[status] ?? status;
}

export type WorkspaceView = "config" | "glossary" | "translate" | "review";

export function viewForStatus(status: string): WorkspaceView {
  if (status === "uploaded") return "config";
  if (["configured", "generating_glossary", "awaiting_review"].includes(status)) {
    return "glossary";
  }
  if (["running", "paused"].includes(status)) return "translate";
  return "review";
}

export function canOpenView(job: Job, view: WorkspaceView) {
  const rank: Record<WorkspaceView, number> = {
    config: 0,
    glossary: 1,
    translate: 2,
    review: 3,
  };
  return rank[view] <= rank[viewForStatus(job.status)];
}

