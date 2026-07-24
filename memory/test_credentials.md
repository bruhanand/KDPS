# KDPS — Test Credentials

Foundation demo logins (seeded by `python manage.py seed_foundation`).
Login at the app root; API at `/api/auth/login`.

| Username | Password | Role | Scope |
|---|---|---|---|
| superadmin | Super@123 | it_admin | all |
| admin | Admin@123 | it_admin | all |
| owner | Owner@123 | owner | all |
| ops1 | Ops@123 | ho_ops | all |
| accounts1 | Acct@123 | accounts | all |
| brand1 | Brand@123 | brand_manager | all |
| wh.patna | Wh@123 | warehouse | all |
| steward | Steward@123 | data_steward | all |
| deo.manager | Store@123 | store_manager | store (DEO) |
| deo.cashier | Store@123 | store_staff | store (DEO) |

`superadmin` is the only Django superuser (break-glass: bypasses the RBAC matrix, reaches `/admin`). Every other login — including `admin` (it_admin) and `owner` — is a normal user enforced by the section-access matrix.
