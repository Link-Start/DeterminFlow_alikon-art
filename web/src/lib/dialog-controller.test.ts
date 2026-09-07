import assert from "node:assert/strict";
import test from "node:test";
import { DialogController } from "./dialog-controller";

test("one global dialog coalesces duplicate triggers without queuing other dialogs", async () => {
  const controller = new DialogController<{ title: string }>();
  const first = controller.open<boolean>("login", { title: "登录" });
  const second = controller.open<boolean>("login", { title: "第二次点击" });
  assert.equal(first, second);
  assert.equal(await controller.open("report", { title: "举报" }), null);
  assert.equal(controller.getSnapshot()?.content.title, "登录");
  controller.settle("login", true);
  assert.equal(await first, true);
  assert.equal(await second, true);
  assert.equal(controller.getSnapshot(), null);
});

test("dismissal resolves waiters and a new explicit click can reopen", async () => {
  const controller = new DialogController<string>();
  const first = controller.open("marketplace:report", "report");
  controller.cancelMatching("marketplace:");
  assert.equal(await first, null);
  const second = controller.open("marketplace:report", "retry");
  assert.notEqual(first, second);
  controller.settle("marketplace:report", true);
  assert.equal(await second, true);
});

test("late results from a dismissed instance cannot close a new dialog with the same key", async () => {
  const controller = new DialogController<object>();
  const oldContent = {};
  const old = controller.open("report", oldContent);
  controller.settle("report");
  await old;
  const newContent = {};
  const current = controller.open("report", newContent);
  controller.settle("report", true, oldContent);
  assert.equal(controller.getSnapshot()?.content, newContent);
  controller.settle("report", false, newContent);
  assert.equal(await current, false);
});

test("scope cleanup does not cancel another feature's global dialog", async () => {
  const controller = new DialogController<string>();
  let changes = 0;
  const unsubscribe = controller.subscribe(() => { changes += 1; });
  const pending = controller.open("account-login", "login");
  controller.cancelMatching("marketplace:");
  assert.equal(controller.getSnapshot()?.key, "account-login");
  controller.cancelMatching("");
  assert.equal(await pending, null);
  assert.equal(changes, 2);
  unsubscribe();
});
