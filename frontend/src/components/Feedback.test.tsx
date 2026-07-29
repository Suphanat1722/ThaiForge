import axe from "axe-core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog, ErrorBanner } from "./Feedback";

describe("feedback components", () => {
  it("announces errors and gives the close control a name", async () => {
    const { container } = render(<ErrorBanner message="โหลดไม่สำเร็จ" onClose={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("โหลดไม่สำเร็จ");
    expect(screen.getByRole("button", { name: "ปิดข้อความ" })).toBeVisible();
    expect((await axe.run(container)).violations).toHaveLength(0);
  });

  it("renders an accessible confirmation dialog", async () => {
    render(
      <ConfirmDialog
        open
        onOpenChange={vi.fn()}
        title="ลบงานนี้?"
        description="ย้อนกลับไม่ได้"
        confirmLabel="ลบงาน"
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByRole("dialog", { name: "ลบงานนี้?" })).toBeVisible();
    expect((await axe.run(document.body)).violations).toHaveLength(0);
  });
});

