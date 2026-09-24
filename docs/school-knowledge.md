# Public school knowledge

The chatbot uses a versioned snapshot of official Brentwood public information in
`data/school_knowledge.json`. Each record has a topic, factual notes, an official
source URL, and the snapshot's verification date. `data/school_sources.json`
records coverage and exclusions. The snapshot contains no student accounts,
private calendar links, personal grades, or inferred student assignments.

Public facts such as the houseparent of Rogers, the contents of the Foote Centre,
library services, IT support, and course descriptions use `SCHOOL_INFO`. The
classifier translates the specific question into English search terms, including
the named person/place and context from follow-up questions. Local lexical search
selects a bounded set of relevant records; the answer must be supported by those
records and link to the official source. Missing information stays unknown.

`PERSONAL_SCHOOL` sends assigned teachers, advisors, classes, houses, roommates,
and student records to MySchool without retrieving public staff data or invoking
the answer model. Personal arts and sports retain their existing MySchool
redirect. Named-house public roles remain answerable. Public program descriptions
do not establish that a student is enrolled or that an activity is running today.

The website snapshot does not replace the live schedule, menu, sign-in, bedtime,
or manually maintained afternoon rules. The midnight calendar sync remains
separate. Website facts are **not automatically refreshed**: staff and facility
changes must be reviewed and committed before deployment.

User curation: omit generic Wi-Fi/network-login instructions and Wi-Fi amenity
details. Keep useful IT support and repair information. A specific staff-role
question should return that role and its source, without unrelated house facts.

## Updating the snapshot

1. Install `beautifulsoup4` in a maintenance environment (not required by the app).
2. Run `python scripts/collect_school_site.py --output /path/to/scratch`.
   This inventories every sitemap, reads the public information and course pages,
   and preserves extracted text/links for review. The historical blog, livestream,
   and taxonomy archives are inventoried separately, not treated as current policy.
3. Review the relevant source pages and update concise factual records. Preserve
   exact names, explicit date/year qualifications, provenance, and unique IDs.
   Do not infer personal assignments, requirements, hours, or staff responsibilities.
   Avoid copying marketing text or storing raw pages in this repository.
4. Update source coverage and the verification date. Check cross-page conflicts;
   prefer the dedicated department page over a broad overview and record decisions.
   Publicly linked external documents are pointers unless their contents are
   separately read and verified. Login-only content must not be marked as read.
5. Run `python -m pytest tests/ -q`, then check representative real questions,
   including a personal assignment, a public role, a facility, and a missing fact.
6. Commit and deploy. The application loads the snapshot once per worker, so a
   service restart is required to load a new version.

## Source conflict decisions for this snapshot

- **Allard house staff:** the September 2026 welcome page lists Kim Waugh as
  Houseparent and Sara Checkley as Assistant Houseparent; the general staff
  directory lists Adriane Rogers and Kim Waugh respectively. Related records
  include both sources and a conflict flag. Answers must disclose the mismatch
  and ask students to confirm with the school, rather than guess who is current.
- **Innovations location:** the dedicated Innovations page says the lower floor
  of the Centre for Innovation and Learning, around the corner from the Science
  Lab. The general student-services page still places IT in Crooks Hall. The
  dedicated page is used; the Crooks IT-location claim is excluded.
- Staff roles are public directory facts, not a student's teacher assignments.
  Source pages may list more than one person with a similar title; do not silently
  select a single person or invent an exclusive/current assignment.
- Opening-day house pages are used for house staff and partner-house facts only.
  Their dated orientation schedules are excluded from regular timetable answers.
