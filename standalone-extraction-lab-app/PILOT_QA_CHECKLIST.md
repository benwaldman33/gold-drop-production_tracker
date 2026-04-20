# Standalone Extraction Lab App Pilot QA Checklist

## Login

- Login succeeds with a user who has extraction workflow access.
- Logout returns the app to the login screen.

## Reactor board

- `Reactors` shows active reactor cards.
- `Board view` filters change the card list correctly.
- Lifecycle buttons update reactor state.
- `Cancel Charge` offers `Abandon charge` and `Cancel and modify run`.

## Lots

- `Lots` search finds results by tracking id, supplier, strain, and batch id.
- a ready lot shows `Ready`
- a not-ready lot still opens with clear warnings

## Charge form

- weight slider updates the large lbs display
- `-5`, `-1`, `+1`, `+5`, and `Full lot` controls work
- reactor segmented buttons work
- `Now` updates the timestamp
- `Record Charge` creates a charge and returns to the board

## Main-app continuity

- after recording a charge, `Open Run in Main App` opens the existing run form
- the new charge also appears on main-app `Floor Ops`
