# Chat usage limits

The feedback in [issue #9](https://github.com/Kyle1-2-3/chat-bot/issues/9) is handled as follows:

- The classifier selects relevant school data and answer instructions. Unknown
  questions receive a clarification prompt, without loading all school data.
- Both model stages receive the current Vancouver date and time in their system
  instructions on every call, including follow-up questions.
- A signed, HttpOnly, SameSite=Lax cookie identifies a returning browser for 30
  days. This is an anonymous browser identifier, not a student account. Clearing
  cookies creates a new identifier; the IP and global limits remain in effect.
- Daily browser/IP counters and Gemini call counters live in a separate SQLite
  database, shared across all three Gunicorn workers and preserved on restarts
  and school-data reseeds. Reservations are atomic and precede the SDK call.

## Configuration

Set these in the server's private `.env`, then restart `chatbot`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `USER_DAILY_LIMIT` | `300` | Accepted messages per browser per school day |
| `IP_DAILY_LIMIT` | `300` | Accepted messages per IP per school day, preserving the previous IP policy |
| `GEMINI_DAILY_CALL_LIMIT` | `1000` | Model calls across this app per school day |
| `USAGE_DB_PATH` | `var/usage.sqlite3` | Persistent usage database, separate from `db/school.db` |

Use `0` to disable an individual limit. Days reset at midnight in
`America/Vancouver`, including daylight-saving changes. `FAKE_TODAY` never
affects usage limits. The IP cap also applies to students sharing a school NAT;
it can be adjusted independently of the browser cap. Nginx's existing shared
10-request/minute IP limit remains in place; Flask also has a minute backstop.

Each SDK invocation reserves one global call. Failed or cancelled calls are not
refunded, and SDK retries are disabled so one invocation cannot silently make
five attempts. A normal AI answer uses up to two calls; direct menu and academic
timetable answers use none. Dev chat uses the same cap. When the global cap is
reached, direct answers can still work within the browser/IP message limits.
Counter failures stop model calls and produce a temporary-unavailable message.

The store contains counters, a cookie signing key, random browser identifiers,
and keyed hashes of IPs; no conversation text or raw IPs. Expired daily counters
are cleaned up during reservations. Keep `var/` private and out of Git and Docker
build contexts. Persist `/app/var` as a Docker volume if using containers. The
current EC2 checkout keeps it across deployments. Do not delete the database to
deploy: that would reset both the limits and the cookie signing key.

## Scope of the cap

This is an application call cap, **not a token or dollar budget** and not a
Google-project-wide quota. It does not cover other applications using the same
project/key. The provider's project quotas/billing settings have not been
verified by this change; the Google project owner must check them separately.
Multiple hosts would require a shared external counter store instead of local
SQLite.

## Reply deadlines

Each Gemini call has a 15-second deadline with no automatic retries. A reply can
use two calls, so `gunicorn.conf.py` gives a worker 45 seconds. Gunicorn loads
that configuration from the working directory in both EC2 and Docker. The
browser's 18-second idle deadline renews on actual progress events. The minimum
one-second display time and four-second progress labels are unchanged.
