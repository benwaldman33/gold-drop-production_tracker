# Standalone Extraction Lab App Pilot QA Checklist

## Login

- Login succeeds with a user who has extraction workflow access.
- Logout returns the app to the login screen.

## Reactor board

- `Reactors` shows active reactor cards.
- `Board view` filters change the card list correctly.
- Lifecycle buttons update reactor state.
- `Cancel Charge` offers `Abandon charge` and `Cancel and modify run`.

## Scan / Enter Lot

- `Scan / Enter Lot` opens from the sidebar and home page.
- the manual tracking-ID field is focused automatically when the scan screen opens.
- manual tracking-ID entry opens the correct lot charge form.
- camera scanning works on supported iPad/Safari environments over HTTPS.
- unsupported browsers show a clear fallback message instead of a broken camera state.
- scan guidance copy is visible on-screen without opening another help panel.

## Lots

- `Lots` search finds results by tracking id, supplier, strain, and batch id.
- a ready lot shows `Ready`
- a not-ready lot still opens with clear warnings

## Charge form

- weight slider updates the large lbs display
- default weight is `100 lbs` when the lot has at least 100 lbs remaining
- `100 lbs`, `Half lot`, `Full lot`, and `Last used` presets work
- `-5`, `-1`, `+1`, `+5`, and `Full lot` controls work
- reactor segmented buttons work and the last-used reactor is preselected on the next charge
- `Now` updates the timestamp
- `Record Charge` creates a charge and returns to the board

## Main-app continuity

- after recording a charge, `Open Run` opens the standalone run-execution screen
- after recording a charge, `Open Run in Main App` opens the existing run form
- `Charge Another Lot` returns the operator to `Scan / Enter Lot`
- the new charge also appears on main-app `Floor Ops`

## Standalone run execution

- `Open Run` shows inherited reactor, source, strain, and biomass weight from the charge
- `Start / Now` and `Stop / Now` buttons stamp the timer fields without typing
- biomass blend slider updates milled / unmilled percentages to total `100`
- saved extraction defaults from `Settings -> Operational Parameters` prepopulate the standalone run screen for new charge-linked runs
- fill, flush, and stringer basket counters respond to `- / +`
- saving the run keeps the reactor-linked workflow intact and leaves `Open in Main App` available
