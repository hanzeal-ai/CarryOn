#!/bin/sh
# Compile/link only. This does not sign, install, or replace an Xcode archive.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output_dir="$project_dir/.build/device-check"
mkdir -p "$output_dir"
ios_sdk=$(xcrun --sdk iphoneos --show-sdk-path)
xcrun swiftc -sdk "$ios_sdk" -target arm64-apple-ios17.0 -swift-version 6 \
  -emit-module -emit-library -static -module-name CarryOnCore \
  "$project_dir"/CarryOn/Core/*.swift \
  -emit-module-path "$output_dir/CarryOnCore.swiftmodule" -o "$output_dir/libCarryOnCore.a"
xcrun swiftc -sdk "$ios_sdk" -target arm64-apple-ios17.0 -swift-version 6 \
  -I "$output_dir" -L "$output_dir" -lCarryOnCore -emit-executable -module-name CarryOn \
  "$project_dir"/CarryOn/App/*.swift -o "$output_dir/CarryOn"
xcrun vtool -show-build "$output_dir/CarryOn"
