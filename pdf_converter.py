"""UDF → PDF with the official UYAP Doküman Editörü (Havelsan) engine only.

Office rule (udf_donusturme_kurallari.md): there is no fallback to another renderer. If the
official engine cannot convert a document, the conversion fails and the reason is reported.

Command line (used by the Finder Quick Action, convert_cli.sh):
    python pdf_converter.py a.udf [b.udf ...]   → a.pdf, b.pdf next to each file
"""

import os
import sys
import tempfile

from java_bridge import NativeConversionError, convert_pairs


def _default_pdf_path(udf_path: str) -> str:
    return os.path.splitext(udf_path)[0] + ".pdf"


def convert_udf_file_to_pdf(udf_path: str, output_path: str | None = None) -> str:
    """Converts one .udf file and returns the PDF path; raises NativeConversionError on failure."""
    udf_path = os.path.abspath(os.path.expanduser(udf_path))
    output_path = os.path.abspath(os.path.expanduser(output_path or _default_pdf_path(udf_path)))
    error = convert_pairs([(udf_path, output_path)]).get(output_path, "bilinmeyen hata")
    if error:
        raise NativeConversionError(
            f"{os.path.basename(udf_path)} PDF'e dönüştürülemedi: {error} "
            "(Kural gereği başka bir motora geçilmedi.)"
        )
    return output_path


def convert_udf_bytes_to_pdf(udf_bytes: bytes, output_path: str) -> str:
    """Converts an in-memory .udf (e.g. one just built from markdown) to PDF."""
    with tempfile.TemporaryDirectory() as tmp:
        udf_path = os.path.join(tmp, "belge.udf")
        with open(udf_path, "wb") as f:
            f.write(udf_bytes)
        return convert_udf_file_to_pdf(udf_path, output_path)


def main(argv: list[str]) -> int:
    pairs = [(p, _default_pdf_path(p)) for p in argv if p.lower().endswith(".udf") and os.path.isfile(p)]
    if not pairs:
        print("Dönüştürülecek .udf dosyası seçilmedi.")
        return 2
    results = convert_pairs(pairs)
    failed = 0
    for udf_path, pdf_path in pairs:
        error = results.get(os.path.abspath(pdf_path), "bilinmeyen hata")
        if error:
            failed += 1
            print(f"HATA\t{os.path.basename(udf_path)}\t{error}")
        else:
            print(f"TAMAM\t{os.path.basename(udf_path)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
