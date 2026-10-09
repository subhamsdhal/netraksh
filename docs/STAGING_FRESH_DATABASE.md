# Fresh installation and historical production data

Revisions e4a6b8c0d2f3, f5b7c9d1e3a4 and a6c8e0f2b4d6 are production account
data repairs, not schema creation. Their expected accounts were provisioned
through application bootstrap during the original deployment; the baseline
schema migration creates the users table without inserting users.

Each repair now returns only if the **entire users table is empty**. This is
necessary in the historical revisions themselves: a later revision cannot run
past an earlier failure. All populated-database guards, row counts, mutations,
transaction boundaries and irreversible downgrades are preserved. Existing
databases that already applied these revisions do not re-execute them.

Fresh installation follows `alembic upgrade head`, then the existing strict
production/staging bootstrap with explicitly supplied strong credentials and
`BOOTSTRAP_USERS=true`. Disable bootstrap after verifying login. Staging users
are newly provisioned accounts, never migrated production identities.

Do not stamp an incomplete schema, invent legacy users, or seed historical
events/evidence/runs to satisfy a repair. A data clone still requires a verified
source backup including its Alembic revision and related media.

Regression coverage is in `tests/integration/test_fresh_install_migrations.py`.
It checks fresh schema/HTTP authentication, populated PostgreSQL account repairs,
audit foreign-key preservation, repeated upgrade, malformed account rejection,
and rollback of the entire repair transaction. PostgreSQL fixtures require
`NETRAKSH_TEST_POSTGRES_URL` pointing to loopback and a `netraksh_test*` database;
each test creates and removes only its own random schema.
