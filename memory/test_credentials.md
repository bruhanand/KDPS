# KDPS — Test Credentials

Foundation demo logins (seeded by `python manage.py seed_foundation` or `python manage.py seed_admin`).
Login at the app root; API at `/api/auth/login`. Auth supports Bearer tokens and httpOnly JWT cookies.

| Username | Password | Role | Scope |
|---|---|---|---|
| admin | Admin@123 | it_admin | all |
| owner | Owner@123 | owner | all |
| ops1 | Ops@123 | ho_ops | all |
| accounts1 | Acct@123 | accounts | all |
| wh.patna | Wh@123 | warehouse | all |
| steward | Steward@123 | data_steward | all |
| deo.manager | Store@123 | store_manager | store (DEO) |
| deo.cashier | Store@123 | store_staff | store (DEO) |

`admin` is the Django superuser (also reaches `/admin`). Passwords are seeded with Django `bcrypt_sha256` hasher, with PBKDF2 fallback for older hashes.
