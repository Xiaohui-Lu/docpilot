import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AnswerView } from "./AskBox";
import { RiskBadge, StatusBadge } from "./ui";

describe("badges", () => {
  it("renders risk levels and handles missing values", () => {
    render(<RiskBadge level="high" />);
    expect(screen.getByText("high risk")).toBeInTheDocument();
    render(<RiskBadge level={null} />);
    expect(screen.getByText("-")).toBeInTheDocument();
  });

  it("shows a spinner for in-flight statuses", () => {
    const { container } = render(<StatusBadge status="processing" />);
    expect(screen.getByText("processing")).toBeInTheDocument();
    expect(container.querySelector(".animate-spin")).not.toBeNull();
  });
});

describe("AnswerView", () => {
  const citation = {
    document_id: "d1",
    document_title: "Master Subscription Agreement",
    chunk_id: "c1",
    chunk_index: 2,
    quote: "90 days' prior written notice",
  };

  it("links citations to the source document", () => {
    render(
      <MemoryRouter>
        <AnswerView answer="You need 90 days' notice [1]" citations={[citation]} />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: /Master Subscription Agreement · section 3/ });
    expect(link).toHaveAttribute("href", expect.stringContaining("/documents/d1?quote="));
    expect(screen.getByText(/"90 days' prior written notice"/)).toBeInTheDocument();
  });

  it("calls onCite instead of navigating when provided", async () => {
    const onCite = vi.fn();
    render(<AnswerView answer="x" citations={[citation]} onCite={onCite} />);
    await userEvent.click(screen.getByRole("button", { name: /section 3/ }));
    expect(onCite).toHaveBeenCalledWith(citation);
  });
});

describe("deadline wording", () => {
  it("describes days left in plain language", async () => {
    const { daysText } = await import("./Deadlines");
    expect(daysText(-3)).toBe("3 days overdue");
    expect(daysText(-1)).toBe("1 day overdue");
    expect(daysText(0)).toBe("Today");
    expect(daysText(1)).toBe("Tomorrow");
    expect(daysText(4)).toBe("In 4 days");
  });
});
