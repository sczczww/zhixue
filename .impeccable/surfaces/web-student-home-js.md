---
version: 1
slug: "web-student-home-js"
primary_target: "web/student-home.js"
related_targets: ["web/student-home.css", "web/index.html", "web/independent.js"]
---

# Student homepage preview

Mode: Operate. Execution: code-led. Scope: the independent student homepage and its active shell. This is a local first-look draft requested on 2026-11-14; campus, counselor and non-home independent pages retain their existing design contract. Both entrances continue sharing rules, data and permissions.

## Direction contract

THESIS: Put B1's academic-risk-to-support workflow first: understand an actual graded warning and its evidence, assess next-term choices, then see counselor follow-up and personal actions.

OWN-WORLD: Retain the user-selected Attio plus Udacity white navigation rail, cool neutral canvas, fine borders, restrained green actions and consistent sans-serif text. The later B1-alignment request replaces course photographs with compact evidence records and promotes risk and support content.

STORY: Read current graded risks and sources, review explicitly conditional next-term credit projections, compare a specific course, inspect the responsible counselor's actual case record, and continue a learning action. The contextual assistant remains part of the warning's next step.

FIRST VIEWPORT: The main column begins with warning severity, evidence, source and an explanatory action; next-term conditional projections and compact course records follow. The right column begins with counselor, current case stage and latest event, followed by personal actions. The broader grade/credit portrait is below. DOM and narrow-screen order is warning, next-term risk, support, actions, then portrait. Desktop support spans the first two main rows without changing DOM order.

FORM: User-selected Attio plus Udacity learning dashboard, code-led. No concept-seed round was run: the user directly selected these two real product references in the preceding comparison, so their choice is the visual authority for this draft. This is a documented exception to the catalog-selection workflow, not an unavailable seed result. Reference files: `../inspection/2026-11-14/ui-references/attio.jpg` and `udacity.jpg`. Rejected incumbent: `../inspection/2026-11-13/railway/live-home.jpg`.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Interaction and truth

- Course record actions open the existing filtered credit-record tab. Compare actions open the actual risk-check page and calculate that course's selected/unselected alternatives; stale navigation is ignored.
- The primary warning shows a source and trigger immediately, while full evidence remains in the existing accessible drawer. Multiple warnings retain total/level counts and the full-list link.
- Counselor state is tied to the named warning and actual case events. Only the current stage is marked; earlier stages are not inferred as completed. The feedback link opens the existing follow-up tab. Student action completion never changes case status.
- Next-term projections come from the existing server report. Passing-current-enrollment assumptions, incomplete coverage, simulated course data and out-of-scope junior estimates stay labeled. Optional plan/risk/event request failures have explicit retry states; they do not masquerade as zero risks or zero actions.
- Action checkboxes use existing persisted completion behavior. Empty action and course states explain an available next step.
- All totals, categories, warnings, status names, GPA notes and dates come from current API results. Pending or incomplete data stays labeled; no effectiveness or accuracy claims are introduced.
- Synthetic demo labels remain visible. The B1-aligned homepage displays no course cover imagery; source image files remain only as records of the prior preview.
- Reduced-motion users receive immediate content. No entrance animation hides the important information.
- Current B1 review evidence lives in `../inspection/2026-11-14/b1-home`; `../inspection/2026-11-14/home-redesign` remains the historical baseline. On 2026-11-14 the user explicitly requested publication and this homepage was deployed to the existing shared Railway demo. Deployment and live verification evidence is in `../inspection/2026-11-14/deploy-b1`. This release does not constitute a real campus integration or whole-application redesign acceptance.
