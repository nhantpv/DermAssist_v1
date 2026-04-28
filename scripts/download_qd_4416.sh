#!/usr/bin/env bash
# Downloads Quyết định 4416/QĐ-BYT 2023 PDF.
# Primary source: hosted by Bệnh viện Hà Trung. Backup: 2015 predecessor.
#
# Usage:
#   ./scripts/download_qd_4416.sh                  # → data/raw/
#   ./scripts/download_qd_4416.sh /custom/dir
set -euo pipefail

OUT_DIR="${1:-data/raw}"
mkdir -p "$OUT_DIR"

PRIMARY_URL="https://benhvienhatrung.vn/wp-content/uploads/2024/02/quyet-dinh-4416-qd-byt-2023-huong-dan-chan-doan-va-dieu-tri-cac-benh-da-lieu.pdf"
BACKUP_URL="https://trungtamthuoc.com/pdf/byt-huong-dan-chan-doan-dieu-tri-da-lieu.pdf"

OUT_FILE="$OUT_DIR/qd-4416-byt-2023.pdf"

if curl -fL --connect-timeout 10 -o "$OUT_FILE" "$PRIMARY_URL"; then
    echo "✓ Downloaded primary source"
else
    echo "Primary failed, trying backup (Quyết định 75/2015)..."
    curl -fL -o "$OUT_DIR/qd-75-byt-2015.pdf" "$BACKUP_URL"
    echo "⚠ Using 2015 backup — verify content covers our 8 conditions"
fi

ls -lh "$OUT_DIR"
