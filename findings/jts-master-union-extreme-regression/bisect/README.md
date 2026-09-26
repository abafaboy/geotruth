# Bisect

`git bisect start master 1.20.0 && git bisect run ./bisect_step.sh` in a full clone of
locationtech/jts (`jts-full/`), with `D` pointing at a directory that holds `jts-full/` and
`java/Check.java`:

- `java/Check.java`: the corpus case as is (max |ordinate| 3.8e220). First bad commit
  4668803 "Add KdTree nearestNeighbor() and nearestNeighbors() (#1114)".
- `check-1.5e162/java/Check.java`: the same case divided by 2^194 (max |ordinate| 1.5e162).
  First bad commit 52c5d988 "OverlayEdge: Don't skip first point when adding coordinates
  (#1187)". 4668803 is an ancestor of 52c5d988, so both changes are present there; at this
  magnitude #1187 is what makes the first four snapping tries fail (see ../ISSUE.md), and the
  fifth then hits the #1114 overflow.

The #1187 step applies to this corpus case only. The minimal triangle
POLYGON ((0 0, 2 1, 1 2, 0 0)) scaled by 2^538 is already empty at 4668803 and at 52c5d988^.

`bisect_log.txt` holds both `git bisect log`s.

`History.java` (public API only) runs four checks on jts-core built at each commit involved
(#1112 aa755818, #1114 4668803, #1187 52c5d988 and their parents), on 1.18.0, 1.20.0, master and
master + ../prototype_fix.diff: `KdTree(0.0)` with points 1e-170 apart, `KdTree(1e155)` with
points 1e300 apart, the first power of two at which the triangle's self-union is empty, and
the 1.5e162 corpus copy. `output_history.txt` holds the results. They show that the
large-tolerance merge starts at #1114, that the tolerance-0 merge at the tiny end comes back
on master with #1112 (1.18.0 has it too; only 1.20.0 does not), and that #1187 only matters for
the corpus case.
