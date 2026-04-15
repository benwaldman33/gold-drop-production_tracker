# Purchasing Agent App Pilot QA Checklist

## Login

- open the standalone app
- log in with a real buyer account
- verify the home screen loads without browser errors

## Supplier Search

- search for an existing supplier
- verify location and counts render
- open a supplier that should already exist

## Duplicate Supplier Warning

- start creating a supplier with a near-match name
- verify duplicate warning appears
- verify user can:
  - use existing supplier
  - confirm new supplier

## Opportunity Creation

- create an opportunity with an existing supplier
- attach one or more opportunity photos
- verify submission succeeds
- verify the new opportunity appears in `My Opportunities`

## Opportunity Edit Lock

- edit the new opportunity before approval
- verify changes save
- approve or commit the opportunity in the main app
- return to the standalone app
- verify the opportunity is now locked from buyer-side edits

## Delivery Recording

- open an approved or committed opportunity
- verify `Record Delivery` is available
- submit delivery details
- attach delivery photos
- verify the status becomes `delivered`

## Main App Review

- open `Purchases`
- verify the purchase row shows:
  - `Mobile app`
  - creator name
  - delivery recorder name when delivered
- open the purchase edit page
- verify it shows:
  - submission origin
  - opportunity intake photos
  - delivery confirmation photos

## Supplier Merge

- create an intentional duplicate supplier through the standalone flow
- open the source supplier in the main app
- preview a merge into the canonical supplier
- verify impact summary counts make sense
- execute merge
- verify the duplicate supplier is archived and marked as merged

## Failure Cases

- bad password should show clean login failure
- backend stopped should show a proxy/backend failure instead of silent breakage
- invalid delivery attempt on a non-approved opportunity should fail cleanly

