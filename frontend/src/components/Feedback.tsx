import * as Dialog from "@radix-ui/react-dialog";
import { AlertTriangle, LoaderCircle, X } from "lucide-react";
import type { ReactNode } from "react";

export function Spinner({ label = "กำลังทำงาน" }: { label?: string }) {
  return (
    <span className="spinner-label" role="status">
      <LoaderCircle className="spinner" aria-hidden="true" />
      {label}
    </span>
  );
}

export function ErrorBanner({
  message,
  onClose,
}: {
  message: string;
  onClose(): void;
}) {
  return (
    <div className="error-banner" role="alert">
      <AlertTriangle aria-hidden="true" />
      <span>{message}</span>
      <button className="icon-button" onClick={onClose} aria-label="ปิดข้อความ">
        <X aria-hidden="true" />
      </button>
    </div>
  );
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  danger = false,
  busy = false,
  onConfirm,
}: {
  open: boolean;
  onOpenChange(open: boolean): void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm(): void;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content">
          <Dialog.Title>{title}</Dialog.Title>
          <Dialog.Description>{description}</Dialog.Description>
          <div className="dialog-actions">
            <Dialog.Close asChild>
              <button className="secondary-button" disabled={busy}>ยกเลิก</button>
            </Dialog.Close>
            <button
              className={danger ? "danger-button" : "primary-button"}
              disabled={busy}
              onClick={onConfirm}
            >
              {busy ? <Spinner /> : confirmLabel}
            </button>
          </div>
          <Dialog.Close asChild>
            <button className="dialog-close icon-button" aria-label="ปิด">
              <X aria-hidden="true" />
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

