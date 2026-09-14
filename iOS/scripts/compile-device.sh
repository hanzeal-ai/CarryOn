#!/bin/sh
# The app uses Swift Package resources; compile/link through Xcode's package graph.
# This does not sign, install, or replace an Xcode archive.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
xcodebuild -project "$project_dir/CarryOn.xcodeproj" -target CarryOn \
  -configuration Debug -sdk iphoneos ARCHS=arm64 CODE_SIGNING_ALLOWED=NO \
  -clonedSourcePackagesDirPath "$project_dir/.build/SourcePackages" \
  SYMROOT="$project_dir/.build/device-check-products" \
  OBJROOT="$project_dir/.build/device-check-intermediates" build
