# Launch Role Coverage

This checklist defines the four operational roles that must be cleanly covered before a production launch. The goal is not perfect UI polish; the goal is that each role has one obvious place to do the daily job and one obvious handoff into the broader system.

## 1. Buyer

Primary surfaces:
- Standalone purchasing app for phone/tablet purchase opportunity intake.
- Main app `Purchasing -> Biomass Purchasing` for weekly targets, field submissions, reviewed opportunities, and office-created opportunities.
- Main app `Purchasing -> Purchases` for approval, pricing, status, and full purchase review.

Launch acceptance:
- Buyer can create a purchase opportunity without using the full admin app.
- Buyer or approver can see whether weekly lbs, spend, and potency targets are on track.
- Purchase handoff into approval and receiving is clear.

## 2. Receiver / Inventory

Primary surfaces:
- Standalone receiving app for dock/intake confirmation, receipt correction, and delivery photos.
- Main app `Inventory -> Inventory` for on-hand lot review, labels, scans, and charge handoff.
- Main app purchase edit page for full purchase-level correction when receiving is no longer editable.

Launch acceptance:
- Receiver can find approved/committed purchases ready for receipt.
- Receiver can confirm delivery, upload photos, and correct receipt details until downstream consumption locks the record.
- Inventory users can find the resulting lots, labels, and scan/charge actions.

## 3. Extractor

Primary surfaces:
- Standalone extraction lab app for reactor board, lot scan/search, charging, booth SOP execution, timers, exception loops, evidence uploads, and initial downstream handoff.
- Main app `Extraction -> Floor Ops` for supervisor/operator floor overview and charge queue visibility.
- Main app run form for full run review and supervisor booth review.

Launch acceptance:
- Extractor can start from a lot scan or reactor board and complete the SOP without navigating the full admin app.
- Timing deviations and exception loops are captured without blocking normal permissive-default operation.
- Supervisor can review booth status, evidence, and deviation decisions from the main app.

## 4. Supervisor / Downstream

Primary surfaces:
- Main app `Downstream -> Supervisor Console` for alerts, reactor/queue status, blocked/stale work, and launch role coverage.
- Main app `Downstream -> Queue Overview` for shared downstream routing.
- Destination pages for GoldDrop, Liquid Loud, Terp Strip, HP Base Oil, and Distillate.
- Main app `Alerts -> Alerts Home` for supervisor notifications and genealogy issues.

Launch acceptance:
- Supervisor has one obvious first page for active work and exceptions.
- Downstream queue owner assignment, blocked/stale status, and next steps are visible.
- Supervisor can jump from the console into the exact destination queue, run, Journey surface, or alert queue needed to resolve work.

## Launch Gate

Before final data/access security work, run one real or realistic lot through:
- buyer opportunity creation
- purchase approval
- receiving confirmation
- inventory label/scan
- extraction charge and booth SOP
- downstream routing
- Journey/genealogy review
- financial actuals or financial flag review

Any failure that prevents a role from completing its daily job is a launch blocker. Cosmetic improvements and lower-frequency reporting refinements should be marked post-launch unless they affect accuracy, auditability, or operator safety.

Track launch readiness in the main app at `Settings -> Launch Readiness`.

Use the in-app register to classify each remaining item as:
- `Launch blocker`: must be resolved before live launch.
- `Pilot blocker`: must be resolved before a controlled pilot.
- `Post-launch`: useful but not required to start.
- `Wishlist`: polish or future expansion.

Deferred future work: `LAUNCH_READINESS_AUDIT_TODO.md` tracks the later hybrid audit-engine enhancements for automated readiness checks. The current blocker register remains a manual launch checklist with audit logging for updates.
