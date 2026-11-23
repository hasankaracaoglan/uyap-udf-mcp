"""Bridge to the official UYAP Doküman Editörü (Havelsan) PDF exporter.

uyap_native_converter.js is run with jjs (Java 8 Nashorn) on the editor's own jars.
uyap_integrator/udf_service.py also imports this module: keep is_native_uyap_available,
convert_via_native_uyap and convert_batch_via_native_uyap compatible.
"""

import os
import shutil
import subprocess
import sys
import unicodedata


class NativeConversionError(RuntimeError):
    """The official UYAP engine could not convert a document."""


def get_uyap_classpath() -> str:
    """Finds UYAP classpath containing all editor jars, supporting macOS Unicode variants."""
    possible_apps = [
        "/Applications/Uyap Doküman Editörü.app",
        "/Applications/Uyap Doküman Editörü.app",
        "/Applications/UYAP Doküman Editörü.app",
        "/Applications/UYAP Doküman Editörü.app",
    ]
    uyap_app = None
    for app in possible_apps:
        if os.path.exists(app):
            uyap_app = app
            break

    if not uyap_app:
        try:
            for entry in os.scandir("/Applications"):
                norm = unicodedata.normalize("NFC", entry.name).lower()
                if "uyap" in norm and "dok" in norm:
                    uyap_app = entry.path
                    break
        except Exception:
            pass

    if uyap_app:
        single_jar = os.path.join(uyap_app, "Contents", "Java", "editor-app.jar")
        if os.path.exists(single_jar):
            return single_jar

        java_dir = os.path.join(uyap_app, "Contents", "Java")
        if os.path.exists(java_dir):
            jars = [os.path.join(java_dir, f) for f in os.listdir(java_dir) if f.endswith(".jar")]
            if jars:
                return ":".join(jars)

    return ""


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _find_converter_js() -> str:
    """Kaynak klasörde (git clone) ya da paket kurulumunda <ortam>/share/uyap-udf-mcp altında arar."""
    candidates = [
        os.path.join(SCRIPT_DIR, "uyap_native_converter.js"),
        os.path.join(sys.prefix, "share", "uyap-udf-mcp", "uyap_native_converter.js"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


CONVERTER_JS = _find_converter_js()


def is_native_uyap_available() -> bool:
    """Checks if macOS has jjs (Java Scripting) and UYAP Doküman Editörü installed."""
    jjs_cmd = shutil.which("jjs")
    if not jjs_cmd:
        return False
    cp = get_uyap_classpath()
    return bool(cp) and os.path.exists(CONVERTER_JS)


def unavailable_reason() -> str:
    if not shutil.which("jjs"):
        return "jjs (Java 8) bulunamadı."
    if not get_uyap_classpath():
        return "UYAP Doküman Editörü /Applications altında bulunamadı."
    if not os.path.exists(CONVERTER_JS):
        return f"Dönüştürücü betiği yok: {CONVERTER_JS}"
    return ""


def convert_pairs(pairs: list[tuple[str, str]]) -> dict[str, str | None]:
    """Converts (udf_path, pdf_path) pairs in one JVM.

    Returns {pdf_path: None on success, else the reason in Turkish}. A pair counts as
    converted only when the script reports it; an existing PDF is never taken as success.
    """
    pairs = [
        (os.path.abspath(os.path.expanduser(u)), os.path.abspath(os.path.expanduser(p)))
        for u, p in pairs
    ]
    if not pairs:
        return {}
    reason = unavailable_reason()
    if reason:
        return {pdf: f"Resmi UYAP motoru kullanılamıyor: {reason}" for _, pdf in pairs}

    cmd = ["jjs", "-J-Djava.awt.headless=true", "-J-Dfile.encoding=UTF-8",
           "-cp", get_uyap_classpath(), CONVERTER_JS, "--"]
    for udf_path, pdf_path in pairs:
        cmd += [udf_path, pdf_path]

    results: dict[str, str | None] = {}
    stdout = ""
    stderr = ""
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=60 + 20 * len(pairs))
        stdout = res.stdout.decode("utf-8", "replace")
        stderr = res.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as e:
        stdout = (e.stdout or b"").decode("utf-8", "replace")
        stderr = "zaman aşımı"
    except Exception as e:
        stderr = str(e)

    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] in ("UYAPCONV-OK", "UYAPCONV-ERR") and parts[1].isdigit():
            i = int(parts[1])
            if i < len(pairs):
                ok = parts[0] == "UYAPCONV-OK"
                results[pairs[i][1]] = None if ok else (parts[2] if len(parts) > 2 else "bilinmeyen hata")

    fallback = stderr.strip().splitlines()[-1] if stderr.strip() else "dönüştürücü sonuç bildirmedi"
    for _, pdf_path in pairs:
        if pdf_path not in results:
            results[pdf_path] = f"Resmi UYAP motoru yanıt vermedi ({fallback})."
        elif results[pdf_path] is None and not (
            os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0
        ):
            results[pdf_path] = "Resmi UYAP motoru başarılı dedi ama PDF oluşmadı."
    return results


def convert_via_native_uyap(udf_path: str, output_path: str) -> bool:
    """Converts UDF to PDF using official Havelsan UYAP engine."""
    out = os.path.abspath(os.path.expanduser(output_path))
    error = convert_pairs([(udf_path, out)]).get(out, "bilinmeyen hata")
    if error:
        print(f"Native UYAP conversion failed: {error}")
        return False
    return True


def convert_batch_via_native_uyap(pairs: list[tuple[str, str]]) -> list[str]:
    """Converts a batch of (udf_path, output_path) pairs in a single JVM process.

    Returns the output paths that were converted, as given by the caller.
    """
    if not pairs:
        return []
    results = convert_pairs(pairs)
    successful = []
    for udf_path, output_path in pairs:
        error = results.get(os.path.abspath(os.path.expanduser(output_path)), "bilinmeyen hata")
        if error:
            print(f"Native UYAP conversion failed ({udf_path}): {error}")
        else:
            successful.append(output_path)
    return successful
