import { expect, test } from "@playwright/test";

const SHOTS = "../docs/images";

test("solve a problem end to end: plan approval, live graph, verified claim, KaTeX report", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Polymath Swarm" })).toBeVisible();

  await page
    .getByTestId("problem-input")
    .fill("Compute the sum of the first 100 prime numbers, and determine whether it is prime.");
  // plan approval is on by default
  await expect(page.getByTestId("approval-toggle")).toBeChecked();
  await page.screenshot({ path: `${SHOTS}/ui-home.png` });
  await page.getByTestId("submit").click();

  // Human-in-the-loop: the supervisor's plan waits for approval.
  await page.waitForURL(/\/runs\/run_/);
  await expect(page.getByTestId("approval")).toBeVisible();
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "awaiting_approval");
  await expect(page.getByTestId("task-compute")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/ui-approval.png` });
  await page.getByRole("button", { name: "Approve plan" }).click();

  // Live updates over SSE until the run completes.
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "completed", {
    timeout: 180_000,
  });
  for (const id of ["compute", "critique", "synthesize"]) {
    await expect(page.getByTestId(`task-${id}`)).toHaveAttribute("data-status", "done");
  }

  // The answer's claim passed the gate on reproduced computation.
  const verified = page.locator('[data-testid="claim"][data-status="verified"]');
  await expect(verified.first()).toBeVisible();
  await expect(verified.first()).toContainText("24133");
  await expect(verified.first()).toContainText("computation");

  // Evidence report with KaTeX-rendered maths, and the cost meter.
  const report = page.getByTestId("report");
  await expect(report).toContainText("Verified claims (1)");
  await expect(report.locator(".katex").first()).toBeVisible();
  await expect(page.getByTestId("cost-usd")).toContainText("$");
  await expect(page.getByTestId("activity")).toContainText("run finished: completed");
  await page.screenshot({ path: `${SHOTS}/ui-run.png`, fullPage: true });
});
