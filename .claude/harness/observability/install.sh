#!/usr/bin/env bash
# ABOUTME: Downloads Vector binary to bin/ — idempotent, platform-aware, pinned version.
# ABOUTME: Run once before first use. Safe to re-run; skips if correct version is present.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$SCRIPT_DIR/bin"
VECTOR_VERSION="0.55.0"

# Detect platform
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Darwin)
    case "$ARCH" in
      arm64)  ARCH_SLUG="arm64"   ; PLATFORM="apple-darwin" ;;
      x86_64) ARCH_SLUG="x86_64" ; PLATFORM="apple-darwin" ;;
      *) echo "Unsupported arch: $ARCH"; exit 1 ;;
    esac
    ;;
  Linux)
    case "$ARCH" in
      aarch64) ARCH_SLUG="aarch64" ; PLATFORM="unknown-linux-musl" ;;
      x86_64)  ARCH_SLUG="x86_64"  ; PLATFORM="unknown-linux-musl" ;;
      *) echo "Unsupported arch: $ARCH"; exit 1 ;;
    esac
    ;;
  *) echo "Unsupported OS: $OS"; exit 1 ;;
esac

VECTOR_BIN="$BIN_DIR/vector"
TARBALL="vector-$VECTOR_VERSION-$ARCH_SLUG-$PLATFORM.tar.gz"
DOWNLOAD_URL="https://github.com/vectordotdev/vector/releases/download/v$VECTOR_VERSION/$TARBALL"

# Check if correct version already installed
if [ -f "$VECTOR_BIN" ]; then
  INSTALLED_VERSION="$("$VECTOR_BIN" --version 2>/dev/null | awk '{print $2}' || true)"
  if [ "$INSTALLED_VERSION" = "$VECTOR_VERSION" ]; then
    echo "vector $VECTOR_VERSION already installed — skipping."
    exit 0
  fi
fi

echo "Installing Vector $VECTOR_VERSION ($ARCH_SLUG-$PLATFORM)..."
mkdir -p "$BIN_DIR"

TMP_TAR="$(mktemp /tmp/vector-XXXXXX.tar.gz)"
curl -fsSL "$DOWNLOAD_URL" -o "$TMP_TAR"

# Extract just the vector binary — tarball path is ./vector-{arch}-{platform}/bin/vector (3 components)
tar -xzf "$TMP_TAR" -C "$BIN_DIR" --strip-components=3 "./vector-$ARCH_SLUG-$PLATFORM/bin/vector"

rm -f "$TMP_TAR"
chmod +x "$VECTOR_BIN"

echo "Installed: $("$VECTOR_BIN" --version)"
