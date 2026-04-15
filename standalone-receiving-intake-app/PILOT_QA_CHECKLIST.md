# Receiving Intake App Pilot QA Checklist

## Login

- sign in with a receiving-capable Gold Drop user
- verify `Home` and `Receiving Queue` load

## Queue

- verify approved purchases appear in the ready queue
- verify committed purchases appear in the ready queue
- verify delivered purchases appear only in the delivered filter

## Receiving Detail

- open one queue item
- verify supplier, strain, expected weight, lot state, and approval metadata render

## Confirm Receipt

- record delivery weight and date
- set receiving location
- set testing status
- submit receipt
- verify status changes to `delivered`

## Delivery Photos

- upload one or more photos from the receive form
- verify they appear on the receiving detail screen
- verify they appear in the main app purchase review screen

## Main App Cross-Check

- open the same purchase in the main Gold Drop app
- verify delivery recorder, delivery notes, and delivery photos are visible
