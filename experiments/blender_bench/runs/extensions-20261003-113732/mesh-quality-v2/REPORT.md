# Saved furniture mesh audit

All five saved assets failed the new evaluated-geometry gate because of
positive-area overlaps between coplanar, same-facing faces. No winding defects
or inward closed shells were detected. This provides a plausible explanation
for the reported flashing; it does not establish that every visual artifact
has the same cause.

| Asset | Overlapping object pairs | Evaluated face pairs |
| --- | ---: | ---: |
| Chair | 6 | 12 |
| Stool | 12 | 16 |
| Bench | 4 | 6 |
| Curved chair | 12 | 16 |
| Table | 12 | 16 |

Typical locations include apron corners and apron/leg connections, chair
back panels and uprights, and bench rails/supports. The per-asset JSON reports
identify the objects and faces for targeted repair. Nonplanar bevel faces and
some normal modifier settings are advisory findings.

The audit opened the assets without saving changes. All five before/after
asset hashes match. Historical experiment scores and usage remain unchanged.
`summary.json` records those hashes, the verifier hash, and failed checks.

The new harness extension exposes the same read-only diagnosis, and future
pilot runs include independent mesh-quality checks. Coplanar overlap coverage
is bounded; this does not comprehensively detect self-intersections, instances,
shader defects or all custom-normal issues. Keep multiple view/light inspections
alongside it. No repairs have been applied to these saved models.
