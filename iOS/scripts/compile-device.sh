#!/bin/sh
# Compile/link only. This does not sign, install, or replace an Xcode archive.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output_dir="$project_dir/.build/device-check"
mkdir -p "$output_dir"
ios_sdk=$(xcrun --sdk iphoneos --show-sdk-path)
xcrun swiftc -sdk "$ios_sdk" -target arm64-apple-ios17.0 -swift-version 6 \
  -emit-module -emit-library -static -module-name ConnectNowCore \
  "$project_dir"/ConnectNow/Core/*.swift \
  -emit-module-path "$output_dir/ConnectNowCore.swiftmodule" -o "$output_dir/libConnectNowCore.a"
xcrun swiftc -sdk "$ios_sdk" -target arm64-apple-ios17.0 -swift-version 6 \
  -I "$output_dir" -L "$output_dir" -lConnectNowCore -emit-executable -module-name ConnectNow \
  "$project_dir"/ConnectNow/App/*.swift -o "$output_dir/ConnectNow"
xcrun vtool -show-build "$output_dir/ConnectNow"
