#!/bin/bash
# Finder Hızlı Eylemi ("UDF'yi PDF'e Çevir"): seçilen .udf dosyalarını resmi UYAP motoruyla
# yanlarına PDF olarak çevirir. Hepsi tek JVM'de çevrilir; sonuç bildirimle gösterilir.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -x "$SCRIPT_DIR/venv/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/venv/bin/python"
elif [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
else
    PYTHON_BIN="python3"
fi

notify() {
    osascript -e 'on run argv' \
        -e 'display notification (item 1 of argv) with title "Kayıpsız UDF Dönüştürücü" sound name (item 2 of argv)' \
        -e 'end run' "$1" "$2"
}

output=$(cd "$SCRIPT_DIR" && "$PYTHON_BIN" -B pdf_converter.py "$@" 2>&1)
ok=$(printf '%s\n' "$output" | grep -c '^TAMAM')
failed=$(printf '%s\n' "$output" | grep -c '^HATA')

if [ "$failed" -gt 0 ]; then
    first_error=$(printf '%s\n' "$output" | grep -m1 '^HATA' | cut -f2- | tr '\t' ' ')
    notify "$ok dosya dönüştürüldü, $failed dosya dönüştürülemedi: $first_error" "Basso"
elif [ "$ok" -gt 0 ]; then
    notify "$ok dosya resmi UYAP motoruyla PDF'e dönüştürüldü." "Glass"
else
    notify "Seçilen dosyalar arasında .udf yok." "Basso"
fi
