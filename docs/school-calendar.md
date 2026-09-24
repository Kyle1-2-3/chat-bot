# Official leave calendar

The bot answers vacation, midterm leave, countdown and return questions through
`SCHOOL_BREAKS`, using structured dates instead of general website search.
`school_calendar.py` reads the public Brentwood Calendar iCal linked from
[the official calendar page](https://www.brentwood.ca/calendar/). It accepts only
explicit school leave titles, not faculty holidays, public observances, rowing
camps or other events containing the word “break”. No login is required.

The checked-in `data/school_calendar.json` is the verified 2026–27 fallback.
Nightly/deploy sync writes `db/school_calendar.json` atomically. Gunicorn reads it
per request, so a nightly refresh needs no restart. Invalid, empty, recurring or
ambiguous leave data fails without overwriting the previous snapshot. Dates are
never projected into an unpublished year. The parser handles the published
non-recurring leave format; changed titles/formats need review.

## Dates verified September 23, 2026

| Leave | Starts | Return to campus / last leave date | Classes resume |
| --- | --- | --- | --- |
| Thanksgiving | October 9, 2026, 1 PM | October 12, 2026 | October 13, 2026 |
| Fall midterm | November 6, 2026, 3 AM | November 11, 2026 | November 12, 2026 |
| Winter | December 11, 2026, 3 AM | January 4, 2027 | January 5, 2027 |
| Winter midterm | February 4, 2027, 3 AM | February 9, 2027 | February 10, 2027 |
| Spring | March 12, 2027, 3 AM | March 30, 2027 | March 31, 2027 |
| May midterm | May 6, 2027, 3 AM | May 11, 2027 | May 12, 2027 |
| Summer departure | June 11, 2027, 3:30 PM | Not published | Not published |

Return dates were separately corroborated on the official Travel pages:
[Thanksgiving](https://travel.brentwood.ca/fall-term/thanksgiving-leave),
[November](https://travel.brentwood.ca/fall-term/november-midterm),
[Winter](https://travel.brentwood.ca/winter-term/winter-break),
[February](https://travel.brentwood.ca/winter-term/winter-midterm),
[Spring](https://travel.brentwood.ca/winter-term/spring-break), and
[May](https://travel.brentwood.ca/spring-term/may-midterm).
That corroboration is retained only while the live start/end dates match. The
Travel pages themselves are not automatically recrawled; a changed date clears
the old return-to-campus detail until it is reviewed. The all-day iCal end is
exclusive; the stored last leave day is inclusive. Class resumption is taken
from a separate explicit calendar event, never inferred from the last leave day.

The live calendar's summer departure is June 11, **2027**. The
[Travel Closing Day page](https://travel.brentwood.ca/spring-term/closing-day)
currently labels its date June 11, **2026**. Retain this source discrepancy for
travel questions and do not use the departure event's end time as a summer return
date. Neither a fall return date nor an individual student's transport is known.

The calendar's 3 AM marker denotes early travel, not everyone's bus pickup.
Thanksgiving begins at 1 PM after morning academics. Full leave days suppress
regular academic/break rows in chatbot answers, while keeping explicit events.
Partial departure days retain the supplied morning timetable. Shared art/sport
patterns are omitted on leave and departure days. After summer departure, through
August only, the regular afternoon pattern remains unconfirmed; the bot does not
claim a known closure interval or guess a return date. A school holiday alone is
never evidence of a student's personal assignments or permission to leave.

Examples: “When is the next break?”, “When do we return from winter break?”,
“봄방학 며칠 남았어?”, “Show all breaks this academic year”, and “December 25 schedule”.
Explicit dates for schedule/afternoon questions are validated separately from
weekday queries, which continue to mean the next occurrence of that weekday.
