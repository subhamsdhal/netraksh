# NETRAKSH migration recovery and backup procedure

This procedure preserves the existing staging system. It does not authorize
camera operations, database replacement, overwriting populated data, or a
Production Vercel cutover. Database expiration on November 8, 2026 is an
accepted temporary limit, not a reason to stop software verification.

## Existing resources

- New workspace: `tea-d9l35b2jnfac73a6mulg`.
- Backend: `srv-db4esjid0e5s73eoq48g`, runtime `18bd20ba`.
- Database: `dpg-db4eopnlk1mc73fq3aig-a`, `netraksh-migration-stage-db`.
- Camera 1: `srv-db4ete3tqb8s73f1vb1g`, `cam-border-01`, edge `70a541c`.
- Camera 2: `srv-db4ets2d0e5s73eotj10`, `cam-checkpoint-01`, edge `998c064`.
- Both intended edges use `https://netraksh-migration-stage-backend.onrender.com`.
- Production remains `https://netraksh.vercel.app/` in the existing project.

## Owner-controlled PostgreSQL backup

Use an installed official PostgreSQL client matching the server major version
(verify each database's version in Render). Perform the
export while the database is accessible, well before expiry. No credential,
connection URL, dump, or private manifest belongs in Git or a report.

1. Select the exact staging database in the new Render workspace. Obtain its
   external host, port, database name, and username from the dashboard. External
   access requires TLS. Preserve the application's existing internal URL. In a
   private PowerShell session, assign those non-secret fields and an encrypted
   output path to variables (for example `$DbHost`, `$DbPort`, `$DbName`,
   `$DbUser`, and `$DumpPath`). Do not put the password in a variable or URL.
2. Choose an owner-controlled encrypted backup directory outside this repository
   and outside any Render ephemeral filesystem. Restrict access to the owner.
3. In a private owner terminal, run the following with real non-secret connection
   fields substituted. Enter the password only at the interactive password
   prompt. Do not use a password-bearing URL or `PGPASSWORD` in shell history.

   ```powershell
   $env:PGSSLMODE = 'require'
   pg_dump --host $DbHost --port $DbPort --username $DbUser --dbname $DbName --password --format=custom --file $DumpPath
   if ($LASTEXITCODE -ne 0) { throw 'Backup failed; retain the database' }
   pg_restore --list $DumpPath
   Get-FileHash -Algorithm SHA256 $DumpPath
   ```

4. Retain the checksum, export time, source database ID/server version, and Alembic
   revision beside the encrypted backup. Keep a second encrypted owner-controlled
   copy. A successful archive listing is not proof of a successful restore.
5. Restore into a separate, empty local PostgreSQL test database with no app or
   workers connected. Use `pg_restore --exit-on-error --single-transaction
   --no-owner --no-acl` and explicitly name that test database. Do not use `--clean`
   against any populated staging or production database.
6. Compare schema/Alembic revision, table counts, primary keys, foreign keys,
   camera identities, user roles, event/evidence chains, tracking sample
   `(analysis_session_id, sequence, frame_index)` identities, run summaries, and
   audit records. Validate original signatures and hashes without rewriting them.
7. Backup frequency must match the owner's tolerated data-loss window. Take a new
   verified backup before any future database restore/cutover. PostgreSQL's dump
   is transactionally consistent, but an independently copied media archive is
   not automatically synchronized with that snapshot.

Before expiry, arrange another verified export and an explicit owner decision
about continued hosting. A future Free replacement, if authorized and available,
also expires; restoring a dump does not extend the current instance's lifetime.
Do not delete the working database to make room for a replacement before backup
and restore validation. There is no guaranteed permanent Free PostgreSQL service.

## Original database recovery

Original workspace: `tea-datpju17lnhs73e9eqc0`, owner
`subhamswdhal@gmail.com`. Original database:
`dpg-dattmjlg1s2s73anfuv0-a`, `netraksh-db-eval`, reported expiry October 29, 2026.
The last API inventory reports `suspended` with suspender `billing`. The exact
quota/account cause requires Billing/Usage or Render Support confirmation.
Do not repeatedly query the suspended database or bypass suspension.

Owner support request (draft only; not submitted):

> Please identify the billing/quota reason for the suspension of workspace
> tea-datpju17lnhs73e9eqc0 and database dpg-dattmjlg1s2s73anfuv0-a. We need a
> legitimate read/export of our existing production PostgreSQL data before its
> reported October 29, 2026 expiry. Is temporary access or an existing export
> available without a paid upgrade? Please confirm retention and any steps the
> owner must take. Do not delete, recreate, reset, or upgrade resources; no paid
> change is authorized. The goal is a pg_dump and recovery of original identifiers
> and records, not generation of replacement data.

If an authentic original dump becomes available, first restore it locally and
validate it. Separately back up the populated staging database. Prepare an
explicit conflict policy for staging users/audit and original accounts/keys;
do not merge rows by username or silently replace identities. The final target
restore and endpoint/credential changes require a reviewed cutover plan.

## Media and source-control recovery

The implementation in `backend/services/video_storage.py` stores these objects
through the application's existing local/S3 storage interface:

- `video-sessions/<camera>/<session>/source.<extension>` and `preview.mp4`;
- `video-sessions/<camera>/<session>.json` source metadata;
- `video-control/<camera>.json` selected source/run/generation state;
- `video-preparation/<camera>/...` original upload/preparation state;
- encrypted evidence objects referenced by database evidence metadata.

A PostgreSQL dump does not include these objects or decryption/signing secrets.
Recover an authorized original object archive plus required keys through secure
owner-controlled channels. Preserve names and object keys. Match camera, source
session, analysis session, generation, byte size, and independently computed
SHA-256 hashes against authentic metadata. An S3 ETag is not always a SHA-256
or an MD5 (for example, multipart objects). Do not treat it as one.

The local files `acceptance-videos/vid 1.mp4`, `vid 2.mp4`, and `vid 3.mp4` are
candidate source files only. Their presence does not prove historical session
lineage. Do not attach them to an old session or regenerate analysis to claim
historical recovery. Screenshots from different dates are not a single run.

## Free storage consequence

With `storage_provider=local` and `storage_durable=false`, files and the JSON
control records can disappear on spin-down, restart, redeploy, or instance
replacement. The database may retain tracking history while the selected source
and media are gone. Restoring a database alone therefore cannot restore playback.

The existing S3 interface is a configuration option, not a reason to redesign
the app. Any additional provider and overage-billing risk require owner approval.
No Supabase, paid Render resource, or MP4-in-PostgreSQL substitution is permitted.

Official references:
- https://render.com/docs/postgresql-backups
- https://render.com/docs/free
- https://render.com/docs/disks

## Acceptance boundaries

Do not count an empty-state navigation check as completed-run restoration.
Live upload/analysis and visual tracking quality require separately authorized
camera operations or authentic recovered runs. Isolated fixture tests must stay
local and must never populate the staging production camera identities/history.
Keep the existing Production frontend unchanged until data and operational
acceptance are resolved or the owner gives an informed alternative decision.
