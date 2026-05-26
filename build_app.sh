#!/bin/bash
# Build TokenSpendie.app — a self-contained, double-clickable launcher you can
# drop on the Dock or Desktop. The Python sources are copied *inside* the bundle
# so it works even when macOS TCC blocks ~/Documents access for launched apps.
set -e

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Token Spendie"
APP="$SRC_DIR/$APP_NAME.app"
RES="$APP/Contents/Resources"

# Pick a python that can draw a menu-bar item. A plain (non-framework) python
# — e.g. /opt/anaconda3/bin/python3 — runs fine but its NSStatusItem never
# appears. Prefer a framework / GUI python that links against the window server.
PIP_PY="$(command -v python3)"          # used only to install deps
PY=""
for cand in \
    "/opt/anaconda3/python.app/Contents/MacOS/python" \
    "$(dirname "$PIP_PY")/../python.app/Contents/MacOS/python" \
    "/Library/Frameworks/Python.framework/Versions/Current/bin/python3" ; do
    if [ -x "$cand" ] && "$cand" -c "import rumps" 2>/dev/null; then
        PY="$cand"; break
    fi
done
# Fall back to whatever python3 is on PATH (may not show an icon).
[ -z "$PY" ] && PY="$PIP_PY"

echo "▸ Source:  $SRC_DIR"
echo "▸ Python:  $PY"

# 1) Deps + icons (install with the standard python; both share site-packages)
"$PIP_PY" -m pip install -q -r "$SRC_DIR/requirements.txt"
[ -f "$SRC_DIR/AppIcon.icns" ] || "$PIP_PY" "$SRC_DIR/make_icons.py"

# 2) Bundle skeleton
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$RES"

# 3) Copy the app's own files into the bundle (self-contained)
cp "$SRC_DIR/token_spendie.py" "$RES/"
cp "$SRC_DIR/menubar_icon.png" "$RES/" 2>/dev/null || true
cp "$SRC_DIR/AppIcon.icns"     "$RES/AppIcon.icns"

# 4) Info.plist — LSUIElement=1 → menu-bar-only (no persistent Dock icon)
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>            <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>     <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>      <string>com.tokenspendie.app</string>
    <key>CFBundleVersion</key>         <string>1.0</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundlePackageType</key>     <string>APPL</string>
    <key>CFBundleExecutable</key>      <string>TokenSpendie</string>
    <key>CFBundleIconFile</key>        <string>AppIcon</string>
    <key>LSUIElement</key>             <true/>
    <key>LSMinimumSystemVersion</key>  <string>11.0</string>
    <key>NSHighResolutionCapable</key> <true/>
</dict>
</plist>
PLIST

# 5) Launcher executable — runs the copy inside the bundle.
#    NOTE: we *detach* python (background + disown) instead of exec'ing it.
#    When launched via LaunchServices (`open`/double-click), an exec'd python
#    stays in the bundle's app slot and its NSStatusItem never appears. Running
#    it detached lets it register fresh as a GUI app, exactly like a Terminal
#    launch, so the menu-bar icon shows reliably.
cat > "$APP/Contents/MacOS/TokenSpendie" <<LAUNCHER
#!/bin/bash
mkdir -p "\$HOME/.config/token_spendie"
pkill -f "token_spendie.py" 2>/dev/null || true
HERE="\$(cd "\$(dirname "\$0")/../Resources" && pwd)"
nohup "$PY" "\$HERE/token_spendie.py" \\
    >> "\$HOME/.config/token_spendie/agent.log" 2>&1 &
disown
LAUNCHER
chmod +x "$APP/Contents/MacOS/TokenSpendie"

# 6) Refresh LaunchServices so the icon shows immediately
touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
    -f "$APP" 2>/dev/null || true

echo "✓ Built: $APP"
echo
echo "Next:"
echo "  • Double-click it, or drag it into Applications / the Dock / the Desktop."
echo "  • Look for the ◈ icon in the menu bar."
echo "  • Re-run this script after editing token_spendie.py to refresh the bundle."
