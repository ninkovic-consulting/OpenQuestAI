#!/bin/sh
# Build the app bundle from macos/Sources with swiftc, no Xcode project.
#
#   macos/build.sh <out.app> <Info.plist> <executable name> <bundle id> <min macOS> [icon.icns]
#
# `vision app build` renders the Info.plist and calls this. The bundle is
# signed ad hoc with a designated requirement on the bundle id alone, so its
# identity (and the permissions macOS gives it) survives a rebuild, and with
# the audio-input entitlement Apple's capture documentation asks for.
#
# With PAYLOAD set to a folder (the standalone build), its contents go into
# Contents/Resources before the bundle is signed. Every Mach-O file in it must
# already be signed; the bundle's seal then covers all of it.
set -eu

if [ "$#" -lt 5 ]; then
    echo "usage: $0 <out.app> <Info.plist> <executable> <bundle id> <min macOS> [icon.icns]" >&2
    exit 2
fi
app=$1 info=$2 executable=$3 bundle_id=$4 min_macos=$5 icon=${6:-}
here=$(cd "$(dirname "$0")" && pwd)
swiftc=${SWIFTC:-$(xcrun --find swiftc 2>/dev/null || true)}
if [ -z "$swiftc" ] || [ ! -x "$swiftc" ]; then
    echo "build.sh: the Swift compiler (swiftc) was not found; install Xcode or run \`xcode-select --install\`." >&2
    exit 127
fi

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$info" "$app/Contents/Info.plist"
printf 'APPL????' > "$app/Contents/PkgInfo"
if [ -n "$icon" ]; then
    cp "$icon" "$app/Contents/Resources/AppIcon.icns"
fi

"$swiftc" -O -swift-version 6 \
    -sdk "$(xcrun --sdk macosx --show-sdk-path)" \
    -target "$(uname -m)-apple-macos$min_macos" \
    -o "$app/Contents/MacOS/$executable" \
    "$here"/Sources/*.swift

if [ -n "${PAYLOAD:-}" ]; then
    ditto "$PAYLOAD" "$app/Contents/Resources"
fi

plutil -lint -s "$app/Contents/Info.plist"
codesign --force --sign - --timestamp=none \
    --identifier "$bundle_id" \
    --requirements "=designated => identifier \"$bundle_id\"" \
    --entitlements "$here/Vision.entitlements" \
    "$app"
codesign --verify --deep --strict "$app"
