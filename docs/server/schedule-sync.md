# Midnight schedule sync

`sync-schedule.timer` refreshes the full upcoming MySchool iCal snapshot every
day at 00:00 America/Vancouver, including both the newly started day and tomorrow.
Use current system timezone data (2026b or newer) so Vancouver's permanent UTC−7
rule is respected after November 2026. Persistent timers catch up after downtime.

The server's private `.env` must contain the current `MSM_ICAL_URL`. Remove
`FAKE_TODAY` and any April demo fixture path before enabling live schedules.
Never commit or print the tokenized feed URL. GitHub Actions installs the tracked
systemd units on deployment; the feed is also refreshed during deployment.

Academic A–F block suffixes become block rows. Assembly, Tutorial and Advisory
remain named timeline items. Other events retain their title and time, including
all-day events. Regular attendance-block activities, seasonal sports and the old
numbered Rock Band classes are excluded. Personal events are not necessarily
school-wide. Unscheduled/free blocks are not present in a personal feed and are
never inferred. Fixed breaks are added only on dates with academic blocks.

A successful fetch replaces all upcoming rows so cancelled/removed events do
not linger. A fetch failure, non-calendar response or parse failure preserves the
existing snapshot. Event names and all-day flags are added through an idempotent
schema migration during sync; no school database reseed is needed for migration.

Verify with `systemctl status sync-schedule.timer`,
`systemctl list-timers sync-schedule.timer` and
`journalctl -u sync-schedule.service -n 20`.
