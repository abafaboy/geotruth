#!/bin/bash
# git bisect run helper: compile jts-core main sources with javac and run Check
set -u
D=${D:-$(pwd)}  # directory holding jts-full/ (a full clone of locationtech/jts) and java/Check.java
SRC=$D/jts-full
OUT=$D/bisect-out
rm -rf $OUT; mkdir -p $OUT/core $OUT/chk
find $SRC/modules/core/src/main/java -name '*.java' > $OUT/srcs.txt
javac -nowarn -encoding UTF-8 --release 8 -J-Xmx1g -d $OUT/core @$OUT/srcs.txt >/dev/null 2>&1 || exit 125
javac -cp $OUT/core -d $OUT/chk $D/java/Check.java 2>/dev/null || exit 125
java -cp $OUT/core:$OUT/chk Check 2>/dev/null
