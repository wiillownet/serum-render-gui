#!/bin/sh
# Assemble "dist/Serum Render.app" from a python-build-standalone interpreter
# with this package and serum-render installed into it. Nothing is frozen:
# the launcher execs a real python3, so serum-render's spawned workers
# re-execute a real interpreter too.
#
# Usage:  sh packaging/build-macos.sh
# Signing (optional):  SIGN_IDENTITY="Developer ID Application: ..." sh packaging/build-macos.sh
# Notarization is a separate step once an Apple Developer account exists:
#   ditto -c -k --keepParent "dist/Serum Render.app" dist/app.zip
#   xcrun notarytool submit dist/app.zip --keychain-profile <profile> --wait
#   xcrun stapler staple "dist/Serum Render.app"
set -eu

PBS_TAG=20260901
PY_VERSION=3.12.14
APP_NAME="Serum Render"
BUNDLE_ID="net.wiillow.serum-render-gui"

cd "$(dirname "$0")/.."
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
case "$(uname -m)" in
  arm64) ARCH=aarch64 ;;
  x86_64) ARCH=x86_64 ;;
  *) echo "unsupported arch: $(uname -m)" >&2; exit 1 ;;
esac
TARBALL="cpython-${PY_VERSION}+${PBS_TAG}-${ARCH}-apple-darwin-install_only.tar.gz"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${TARBALL}"

APP="dist/${APP_NAME}.app"
RES="$APP/Contents/Resources"
mkdir -p build dist
[ -f "build/$TARBALL" ] || curl -fL -o "build/$TARBALL" "$URL"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$RES"
tar -xzf "build/$TARBALL" -C "$RES"           # extracts to Resources/python
PY="$RES/python/bin/python3"
"$PY" -m pip install --quiet --no-warn-script-location --upgrade pip
"$PY" -m pip install --quiet --no-warn-script-location .
rm -rf "$RES/python/lib/python3.12/test" "$RES/python/lib/python3.12/idlelib" \
       "$RES/python/lib/python3.12/tkinter" "$RES/python/share"
find "$RES/python" -name __pycache__ -type d -prune -exec rm -rf {} +

# PySide6-Essentials ships Qt Quick, Designer, the QML tooling and every Qt
# module. The app imports QtCore, QtGui and QtWidgets; QtSvg and QtDBus are
# what those and the cocoa/svg plugins link (checked with otool). ~330MB -> ~90MB.
PS="$RES/python/lib/python3.12/site-packages/PySide6"
KEEP_MODULES="QtCore QtGui QtWidgets QtSvg QtDBus"
for f in "$PS"/*.abi3.so; do
  m=$(basename "$f" .abi3.so)
  case " $KEEP_MODULES " in *" $m "*) ;; *) rm -f "$f" "$PS/$m.pyi" ;; esac
done
for fw in "$PS"/Qt/lib/*.framework; do
  m=$(basename "$fw" .framework)
  case " $KEEP_MODULES " in *" $m "*) ;; *) rm -rf "$fw" ;; esac
done
rm -rf "$PS"/Assistant.app "$PS"/Designer.app "$PS"/Linguist.app "$PS"/doc "$PS"/include \
       "$PS"/glue "$PS"/typesystems "$PS"/lrelease "$PS"/lupdate "$PS"/qml* "$PS"/scripts \
       "$PS"/libpyside6qml* "$PS"/Qt/qml "$PS"/Qt/libexec "$PS"/Qt/translations
for d in "$PS"/Qt/plugins/*; do
  case "$(basename "$d")" in platforms|imageformats|iconengines|styles) ;; *) rm -rf "$d" ;; esac
done
rm -f "$PS"/Qt/plugins/platforms/libqminimal.dylib
find "$PS/Qt/plugins/imageformats" -name "*.dylib" ! -name "libqsvg.dylib" -delete

cp assets/icon.icns "$RES/icon.icns"
cat > "$APP/Contents/MacOS/launcher" <<'SH'
#!/bin/sh
here="$(cd "$(dirname "$0")/.." && pwd)"
exec "$here/Resources/python/bin/python3" -m serum_render_gui "$@"
SH
chmod +x "$APP/Contents/MacOS/launcher"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>${APP_NAME}</string>
  <key>CFBundleIdentifier</key><string>${BUNDLE_ID}</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.music</string>
</dict></plist>
PLIST

if [ -n "${SIGN_IDENTITY:-}" ]; then
  codesign --force --deep --options runtime --timestamp -s "$SIGN_IDENTITY" "$APP"
  codesign --verify --deep --strict "$APP"
fi
echo "built $APP ($(du -sh "$APP" | cut -f1))"
