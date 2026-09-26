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

`bisect_log.txt` holds both `git bisect log`s.
