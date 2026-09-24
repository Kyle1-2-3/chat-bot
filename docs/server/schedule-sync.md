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

## Shared afternoon rules

These are manually maintained in `app.py:afternoon_rules`, separate from personal
iCal entries. Monday, Wednesday and Friday are Art Days, 14:00–18:00, with four
one-hour slots (1: 14:00–15:00 through 4: 17:00–18:00). A student has 2–4 arts;
the chatbot cannot determine which ones or which slots are assigned to them.
Tuesday, Thursday and Saturday are Sport Days, with activities somewhere within
14:00–18:00; each sport's exact timing varies. No Sunday pattern has been supplied.

General afternoon/day/block questions use these common rules. Personal arts,
sports and assigned-time questions redirect to the student SSO MySchool link and
My Schedule. Full-day answers include the common afternoon pattern without
inserting art blocks into the academic A–F block order. The pattern is not a
confirmation of normal activities on a holiday or special-event day.
