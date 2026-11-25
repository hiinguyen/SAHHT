#!/usr/bin/env bash
# Build gm-app/build/sahht-gm.apk with the Android SDK command-line tools (no Gradle).
# Needs: JDK, build-tools (aapt2, d8, zipalign, apksigner) and platforms;android-34, e.g.
#   sdkmanager --install "platforms;android-34"
# The APK is signed with the debug key (~/.android/debug.keystore): fine for sideloading.
set -euo pipefail

SDK=${ANDROID_HOME:-$HOME/Android/Sdk}
BT=${BUILD_TOOLS:-$SDK/build-tools/$(ls "$SDK/build-tools" | sort -V | tail -1)}
JAR=$SDK/platforms/android-34/android.jar
KEYSTORE=${KEYSTORE:-$HOME/.android/debug.keystore}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$HERE/build

[ -f "$JAR" ] || { echo "thiếu $JAR: sdkmanager --install \"platforms;android-34\"" >&2; exit 1; }
rm -rf "$OUT" && mkdir -p "$OUT/compiled" "$OUT/classes"

"$BT/aapt2" compile --dir "$HERE/res" -o "$OUT/compiled"
"$BT/aapt2" link -o "$OUT/base.apk" -I "$JAR" --manifest "$HERE/AndroidManifest.xml" \
    -A "$HERE/assets" --min-sdk-version 26 --target-sdk-version 34 \
    --version-code 1 --version-name 1.0 "$OUT"/compiled/*.flat
javac --release 8 -Xlint:-options -classpath "$JAR" -d "$OUT/classes" \
    $(find "$HERE/src" -name '*.java')
"$BT/d8" --lib "$JAR" --min-api 26 --output "$OUT" $(find "$OUT/classes" -name '*.class')
(cd "$OUT" && zip -q base.apk classes.dex)
"$BT/zipalign" -f 4 "$OUT/base.apk" "$OUT/aligned.apk"
"$BT/apksigner" sign --ks "$KEYSTORE" --ks-pass pass:android --key-pass pass:android \
    --out "$OUT/sahht-gm.apk" "$OUT/aligned.apk"
"$BT/apksigner" verify "$OUT/sahht-gm.apk"
echo "OK: $OUT/sahht-gm.apk"
