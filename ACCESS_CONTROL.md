# Access Control

`Settings -> Access Control` is the operating screen for grants and revokes. User creation stays in `Settings -> Users & Access`; this screen controls what an existing user can do.

## Model

- Role templates define the default permissions for `viewer`, `super_buyer`, `user`, and `super_admin`.
- Per-user overrides can add `grant` permissions or remove `revoke` permissions without changing the user's role.
- `super_admin` remains allowed for every permission.
- Revokes win over role-template defaults.

## Protected Action Areas

- Import permissions are separate from view/edit access: `purchasing.import` and `inventory.import`.
- Export permissions are separate from view access: `purchasing.export`, `inventory.export`, `runs.export`, `finance.export`, and `journey.export`.
- Standalone app write access uses `standalone.purchasing`, `standalone.receiving`, and `standalone.extraction` plus the matching workflow permission.
- Journey finance actions use dedicated permissions for financial export, revenue recording, revenue voiding, and genealogy correction.

## Operating Rule

Grant section access by role when possible. Use per-user grants for temporary exceptions and per-user revokes for tighter controls, such as new employees who can view a section but should not import, export, void revenue, or approve deviations yet.
