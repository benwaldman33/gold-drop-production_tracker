import test from "node:test";
import assert from "node:assert/strict";
import { canConfirmReceipt, canEditReceipt, isReceiptClosed, normalizeText, receivingTitle } from "../src/domain.js";

test("normalizeText collapses whitespace and lowercases", () => {
  assert.equal(normalizeText("  Dock   A "), "dock a");
});

test("receipt confirmation allowed only from approved or committed", () => {
  assert.equal(canConfirmReceipt("approved"), true);
  assert.equal(canConfirmReceipt("committed"), true);
  assert.equal(canConfirmReceipt("delivered"), false);
});

test("closed receipt states are delivered, cancelled, or complete", () => {
  assert.equal(isReceiptClosed("delivered"), true);
  assert.equal(isReceiptClosed("complete"), true);
  assert.equal(isReceiptClosed("approved"), false);
});

test("receivingTitle uses supplier and strain names", () => {
  assert.equal(receivingTitle({ supplier: { name: "Farmlane" }, strain_name: "Blue Dream" }), "Farmlane - Blue Dream");
});

test("canEditReceipt follows receiving editability from payload", () => {
  assert.equal(canEditReceipt({ receiving: { receiving_editable: true } }), true);
  assert.equal(canEditReceipt({ receiving: { receiving_editable: false } }), false);
});
