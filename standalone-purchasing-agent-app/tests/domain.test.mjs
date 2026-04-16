import test from "node:test";
import assert from "node:assert/strict";
import {
  canRecordDelivery,
  findDuplicateSupplierCandidates,
  isOpportunityEditable,
  normalizeText,
  opportunityTitle,
} from "../src/domain.js";

test("normalizeText collapses whitespace and lowercases", () => {
  assert.equal(normalizeText("  Farmlane   West "), "farmlane west");
});

test("opportunity editable only before approval", () => {
  assert.equal(isOpportunityEditable("submitted"), true);
  assert.equal(isOpportunityEditable("under_review"), true);
  assert.equal(isOpportunityEditable("approved"), false);
  assert.equal(isOpportunityEditable("delivered"), false);
});

test("delivery only allowed from approved or committed", () => {
  assert.equal(canRecordDelivery("approved"), true);
  assert.equal(canRecordDelivery("committed"), true);
  assert.equal(canRecordDelivery("submitted"), false);
});

test("fuzzy duplicate supplier detection finds close names", () => {
  const matches = findDuplicateSupplierCandidates("Farmlane", [
    { id: "1", name: "Farmlane West", phone: "555-0001", email: "farmlane@example.com" },
    { id: "2", name: "Blue Coast Farms", phone: "555-0002", email: "blue@example.com" },
  ]);

  assert.equal(matches.length, 1);
  assert.equal(matches[0].id, "1");
  assert.ok(matches[0].match_reason.length > 0);
});

test("opportunityTitle uses supplier and strain names", () => {
  assert.equal(opportunityTitle({ supplier: { name: "Farmlane" }, strain_name: "Blue Dream" }), "Farmlane - Blue Dream");
});
