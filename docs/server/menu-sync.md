# Menu freshness

`sync-menus.timer` checks the official [school menu](https://food.brentwood.ca/)
every five minutes on Mondays, when the weekly menu changes. Tuesday through
Sunday retain the existing once-daily 04:00 refresh. All times use America/Vancouver.
The existing `sync_menus.py` reads the
same public Firestore weekly-menu document as the school site and updates the
shared Junior/Senior meal records. Gunicorn reads the database per request;
menu updates do not require an application restart. Grade-specific sign-in rules
are applied separately from the menu text.

Previously, the server-only timer ran once at 04:00 local time. On September 28,
2026, it saved the Mediterranean Chicken Bowl lunch at 04:00; the school then
changed its public document at 10:49:59 to Thai Drunken Noodle Bowl. The chatbot
continued answering from the early-morning copy. The Monday five-minute schedule
catches the weekly change even when the school publishes it after the morning sync.

Deployment installs and enables both tracked menu units, performs an immediate
menu sync, and checks that the timer is active. Persistent timers catch up after
downtime. On Mondays, a healthy refresh can lag a school edit by up to approximately
five minutes. On other days, changes are picked up at the next scheduled refresh.
A failed fetch preserves the existing menu and the next run retries.

To verify:

```sh
systemctl status sync-menus.timer
systemctl list-timers sync-menus.timer
journalctl -u sync-menus.service -n 20
systemd-analyze calendar --iterations=3 'Mon *-*-* *:00/5:00 America/Vancouver'
systemd-analyze calendar --iterations=3 'Tue..Sun *-*-* 04:00:00 America/Vancouver'
```

Do not confuse this with `sync-schedule.timer`, which refreshes academic blocks,
events and leaves at midnight. The menu source contains weekday labels, not
individual dated meal records; the sync mirrors the school's currently published
weekly menu rather than predicting unpublished menus.
