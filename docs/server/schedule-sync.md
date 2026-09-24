# Midnight schedule sync

`sync-schedule.timer` refreshes the full upcoming MySchool iCal snapshot every
day at 00:00 America/Vancouver, including both the newly started day and tomorrow.
Use current system timezone data (2026b or newer) so Vancouver's permanent UTC−7
rule is respected after November 2026. Persistent timers catch up after downtime.

The timer and deployment now run `python sync_school_data.py`, which independently
refreshes the official public school leave calendar and the personal MySchool
feed. A failed public fetch preserves the last leave snapshot and still attempts
the block sync; either failure makes the job fail visibly in systemd/CI.
See [the leave calendar notes](../school-calendar.md) for sources and date semantics.

The server's private `.env` must contain the current `MSM_ICAL_URL`. Remove
`FAKE_TODAY` and any April demo fixture path before enabling live schedules.
Never commit or print the tokenized feed URL. GitHub Actions installs the tracked
systemd units on deployment; the feed is also refreshed during deployment.

Academic A–F block suffixes anchor the actual date's rotation. A personal feed
omits free periods, so it cannot by itself represent the school's full timetable.
`complete_common_timetable` matches at least two distinct academic periods,
including their exact start/end times, to the school's
[official rotation and period table](https://www.brentwood.ca/why-brentwood/unique-timetable/)
(verified 2026-09-23). A unique match completes any missing block, not just F.
Weekdays use ABC, DEF, CAB, FDE, BCA or EFD; Saturday uses ABC or DEF. Wednesday
and Saturday have their own period times. No rotation is advanced by calendar
arithmetic across weekends, holidays or special days.

For example, September 24's D at 10:25 and E at 11:55 establish the FDE day;
the common F period is restored at 08:15–09:35 even when the feed owner is free.
Confirmed normal mornings also receive missing Advisory (Monday), Tutorial
(Tuesday/Friday), or Assembly (Thursday), 09:55–10:20. An explicitly supplied
named period retains its own time. Fixed breaks/inspection are added once.

Empty, event-only, Sunday, sparse, conflicting and nonstandard-period dates are
not completed. A full class cancellation that is indistinguishable from a
personal free period still requires a school-wide exception source; this is a
regular common timetable, not proof of a student's enrolment or attendance.
Check this published template if the school changes its rotation or bell times.

Other events retain their title and time, including all-day events. Regular
attendance-block activities, seasonal sports and the old numbered Rock Band
classes are excluded. Personal events remain separate from school block rows
and are not necessarily school-wide or a cancellation of the common block.

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
