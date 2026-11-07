"""UYAP UDF MCP server.

Claude'un UYAP Doküman Editörü .udf formatında dilekçe üretmesini sağlar.

Hem yerel (stdio) hem cloud (HTTP) transport destekler:
  - python server.py            → stdio (Claude Code/Desktop)
  - python server.py --http     → HTTP, $PORT veya 8000

Cloud deploy'da çıktı dosya yoluna yazılmaz; base64 olarak döner.
Yerel deploy'da output_path verilirse yalnızca diske yazılır (base64 dönmez).

Tool'lar:
  - create_udf_from_markdown: Markdown benzeri metin → .udf (en pratik)
  - create_udf: Yapılandırılmış paragraflar → .udf
  - read_udf / read_udf_from_base64: .udf metnini (istenirse biçimiyle) okur
  - convert_udf_to_pdf / convert_markdown_to_pdf: resmi UYAP motoruyla PDF
"""

from __future__ import annotations

import base64
import io
import os
import re
import sys
import zipfile
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from udf import (
    Paragraph,
    Run,
    TextSanitizer,
    UdfDocument,
    build_content_xml,
    document_text,
    paragraphs_from_dict,
    paragraphs_to_dict,
    read_udf_document,
)

mcp = FastMCP("uyap-udf")


# ----------------------------------------------------------------------------
# Markdown benzeri parser
# ----------------------------------------------------------------------------

INLINE_PATTERN = re.compile(
    r"(\*\*\*(.+?)\*\*\*)|(\*\*(.+?)\*\*)|(__(.+?)__)|(\*(.+?)\*)|(_(.+?)_)",
    re.DOTALL,
)


def _parse_inline(text: str) -> list[Run]:
    runs: list[Run] = []
    pos = 0
    for m in INLINE_PATTERN.finditer(text):
        if m.start() > pos:
            runs.append(Run(text=text[pos : m.start()]))
        if m.group(1):
            runs.append(Run(text=m.group(2), bold=True, italic=True))
        elif m.group(3):
            runs.append(Run(text=m.group(4), bold=True))
        elif m.group(5):
            runs.append(Run(text=m.group(6), underline=True))
        elif m.group(7):
            runs.append(Run(text=m.group(8), italic=True))
        elif m.group(9):
            runs.append(Run(text=m.group(10), italic=True))
        pos = m.end()
    if pos < len(text):
        runs.append(Run(text=text[pos:]))
    if not runs:
        runs.append(Run(text=text))
    return runs


# Bölüm başlıkları numaralandırmayı yeniden başlatır. Anahtar kelimeler tam kelime olarak aranır;
# sıra önemlidir ("DELİLLER VE HUKUKİ NEDENLER" → DIGER, "İTİRAZ NEDENLERİ" → ACIKLAMALAR).
SECTION_WORDS = (
    ("ACIKLAMALAR", {"AÇIKLAMALAR", "AÇIKLAMA", "AÇIKLAMALARIMIZ", "BEYANLARIMIZ", "BEYANLAR",
                     "NEDENLERİ", "NEDENLERİMİZ", "SEBEPLERİ", "SEBEPLERİMİZ", "İTİRAZLARIMIZ",
                     "OLAYLAR", "VAKIALAR"}),
    ("SONUC", {"SONUÇ", "NETİCE", "NETİCE-İ", "NETİCEİ"}),
    ("DIGER", {"DELİLLER", "DELİL", "DELİLLERİMİZ", "EKLER", "EK", "NEDENLER", "SEBEPLER",
               "DAYANAK", "DAYANAKLAR"}),
)

# Büyük harfle yazılmasa da başlık sayılan tam etiketler ("Ek:", "Sonuç ve İstem:" gibi)
SECTION_LABELS = {
    "AÇIKLAMALAR", "AÇIKLAMA", "BEYANLARIMIZ", "İTİRAZ NEDENLERİ", "İSTİNAF NEDENLERİ",
    "İSTİNAF SEBEPLERİ", "TEMYİZ NEDENLERİ", "TEMYİZ SEBEPLERİ", "SONUÇ", "SONUÇ VE İSTEM",
    "SONUÇ VE TALEP", "NETİCE", "NETİCE-İ TALEP", "NETİCE VE TALEP", "DELİLLER", "HUKUKİ DELİLLER",
    "HUKUKİ NEDENLER", "HUKUKİ SEBEPLER", "EKLER", "EK", "EK LİSTESİ",
}


def _tr_upper(s: str) -> str:
    return s.replace("i", "İ").replace("ı", "I").upper()


def _section_kind(body: str) -> str | None:
    """Satır bir bölüm başlığıysa ("AÇIKLAMALAR :", "SONUÇ VE İSTEM :", "DELİLLER :") türünü döndürür.

    Başlık; büyük harfle yazılmış kısa bir etikettir (iki noktadan sonra metin gelebilir).
    Gövdedeki "Sonuç olarak ...", "Ekte sunulan ..." gibi cümleler başlık sayılmaz.
    """
    text = body
    for prefix in ("||", "#|", "|", "#"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    plain = text.replace("*", "").replace("_", "").strip()
    has_colon = ":" in plain
    label = " ".join(plain.split(":", 1)[0].split())
    words = _tr_upper(label).split()
    if not words or re.match(r"^(\d+|[IVXL]+)[.)]", label):
        return None
    if has_colon:
        if len(words) > 6:
            return None
    elif len(words) > 4 or label.endswith("."):
        return None
    kind = next((k for k, keys in SECTION_WORDS if any(w in keys for w in words)), None)
    if kind and (label == _tr_upper(label) or " ".join(words) in SECTION_LABELS):
        return kind
    return None


# Times New Roman karakter genişlikleri (1000 birimlik em). Künye satırında değerin başladığı
# noktayı bulmak için yeterli; tabloda olmayan karakter 500 sayılır.
def _width_table(groups: dict[int, str]) -> dict[str, int]:
    return {ch: w for w, chars in groups.items() for ch in chars}


_TIMES_REGULAR = _width_table({
    250: " .,", 278: ":;/iıjlt", 333: "-()frIİ", 389: "Jsş", 444: "acçez",
    500: "0123456789bdgğhknopquüvxyö", 556: "FPSŞ", 611: "ELTZ", 667: "BCÇR",
    722: "wADGĞHKNOÖQUÜVXY", 778: "m", 889: "M", 944: "W",
})
_TIMES_BOLD = _width_table({
    250: " .,", 278: "/iıl", 333: ":;-()fjt", 389: "IİsşJ", 444: "cçerz",
    500: "0123456789agğovxyö", 556: "bdhknpquüSŞ", 611: "FP", 667: "BELTZ",
    722: "wACÇDNRUÜVXY", 778: "GĞHKOÖQ", 833: "m", 944: "M", 1000: "W",
})
TAB_STOP = 72.0  # TabSet yazılmadığında UYAP her 72 pt'de bir TAB durağı koyar
KUNYE_LINE = re.compile(r"^([^\t:]*)(\t+)( *: *)(?=\S)")      # "DAVACI\t\t: değer"
KUNYE_CONTINUATION = re.compile(r"^()(\t+)( *)(?=\S)")         # "\t\t  2- ikinci taraf"


def _kunye_hanging(runs: list[Run]) -> float | None:
    """Künye satırında iki noktanın durduğu TAB konumunu (pt) döndürür; künye satırı değilse None.

    Değer alt satıra taşarsa UYAP'ın sol kenara dönmemesi için bu değer paragrafın asılı girintisi
    (Hanging) olarak yazılır; taşan satırlar iki nokta sütununun hizasından devam eder
    (kullanıcının UYAP'ta elle yaptığı ayar, 04.11.2026).
    """
    chars = [(ch, r.bold, r.size or 12) for r in runs for ch in r.text]
    text = "".join(c[0] for c in chars)
    m = KUNYE_LINE.match(text) or KUNYE_CONTINUATION.match(text)
    if not m:
        return None
    start, end = m.span(1)
    x = sum((_TIMES_BOLD if b else _TIMES_REGULAR).get(ch, 500) * size / 1000
            for ch, b, size in chars[start:end])
    for _ in m.group(2):
        x = (int(x // TAB_STOP) + 1) * TAB_STOP
    return x


def _markdown_to_paragraphs(md: str) -> list[Paragraph]:
    """Her satır = yeni paragraf. Boş satırlar atlanır (boşluk için <br>).

    Satır başı işaretleri create_udf_from_markdown açıklamasındadır.
    """
    paragraphs: list[Paragraph] = []

    in_aciklamalar = False
    current_section = None
    current_indent = None
    next_available_list_id = 1
    active_roman_list_id = 1
    active_digit_list_id = 2
    has_seen_roman = False

    for raw in md.split("\n"):
        body = raw.rstrip("\r").replace("\\t", "\t")
        if body.strip() == "":
            continue
        if body.strip() == "<br>":
            paragraphs.append(Paragraph(runs=[Run(text=" ")], left_indent=current_indent if in_aciklamalar else None))
            continue

        section = _section_kind(body)
        if section:
            in_aciklamalar = True
            current_section = section
            active_roman_list_id = next_available_list_id
            active_digit_list_id = next_available_list_id + 1
            next_available_list_id += 2
            current_indent = None
            has_seen_roman = False

        alignment = 3
        left_indent: float | None = None
        hanging: float | None = None
        numbered = False
        number_type = None
        list_level = None
        list_id = None
        is_header = False

        # Varsayılan boşluk 8.503938 (0.3 cm)
        space_below: float | None = 8.503938

        if body.startswith(">>>"):
            body = body[3:].lstrip()
            left_indent = 27.777779
            runs = _parse_inline(body)
        elif body.startswith("||"):
            body = body[2:].lstrip()
            alignment = 2
            space_below = 2.834646
            runs = _parse_inline(body)
        elif body.startswith("@|"):
            body = body[2:].lstrip()
            alignment = 1
            space_below = 2.834646
            is_header = True
            if body == "<br>":
                runs = [Run(text="\n")]
            else:
                runs = _parse_inline(body)
        elif body.startswith("@"):
            body = body[1:].lstrip()
            alignment = 1
            space_below = 2.834646
            is_header = True
            runs = _parse_inline(body)
        elif body.startswith("#|"):
            body = body[2:].lstrip()
            alignment = 1
            space_below = 2.834646
            runs = _parse_inline(body)
            for r in runs:
                r.size = 14
        elif body.startswith("#"):
            body = body[1:].lstrip()
            space_below = 2.834646
            runs = _parse_inline(body)
            for r in runs:
                r.size = 14
        elif body.startswith("|"):
            body = body[1:].lstrip()
            alignment = 1
            space_below = 2.834646
            runs = _parse_inline(body)
        elif body.startswith(":::"):
            body = body[3:].lstrip()
            left_indent = 150.0
            runs = _parse_inline(body)
        else:
            runs = _parse_inline(body)

            if not in_aciklamalar:
                hanging = _kunye_hanging(runs)
            else:
                first_non_empty = next((r for r in runs if r.text.strip()), None)
                if first_non_empty:
                    # Match standard digits (1., 2.) OR Roman numerals (I., II., IV., etc.)
                    m = re.match(r"^(\s*)(\d+|I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX)\.(\s+)(.*)", first_non_empty.text)
                    if m:
                        numbered = True

                        # Determine if it's a digit or Roman numeral
                        val = m.group(2)
                        if val.isdigit():
                            number_type = "NUMBER_TYPE_NUMBER_DOT"
                            list_id = active_digit_list_id
                            list_level = 1 # Tüm listeler level 1 olmalı ki UYAP a, b, c yapmasın

                            if current_section == "ACIKLAMALAR" and has_seen_roman:
                                left_indent = 50.0 # Alt liste daha içeriden başlasın
                                current_indent = 50.0
                            else:
                                left_indent = 25.0 # SONUÇ gibi kısımlarda veya tek liste ise ana liste gibi hizala
                                current_indent = 25.0
                        else:
                            has_seen_roman = True
                            number_type = "NUMBER_TYPE_NUMBER_DOT" # Kullanıcı roma rakamları yerine normal sayılar istedi
                            list_id = active_roman_list_id
                            list_level = 1 # Ana liste
                            left_indent = 25.0 # Ana liste
                            current_indent = 25.0
                            # Yeni bir roma rakamı geldiğinde, alt liste id'sini yenile ki 1'den başlasın
                            active_digit_list_id = next_available_list_id
                            next_available_list_id += 1

                        first_non_empty.text = m.group(1) + m.group(4)
                    else:
                        left_indent = current_indent

        paragraphs.append(
            Paragraph(
                runs=runs,
                alignment=alignment,
                left_indent=left_indent,
                hanging=hanging,
                space_below=space_below,
                numbered=numbered,
                number_type=number_type,
                list_level=list_level,
                list_id=list_id,
                is_header=is_header
            )
        )
    return paragraphs


# ----------------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------------

def _paragraphs_to_udf(paragraphs: list[Paragraph]) -> tuple[bytes, list[str]]:
    """In-memory .udf (ZIP) üretir; UYAP'ın açamayacağı karakterler için uyarıları da döndürür."""
    sanitizer = TextSanitizer()
    content_xml = build_content_xml(paragraphs, sanitizer=sanitizer)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("content.xml", content_xml.encode("utf-8"))
    return buf.getvalue(), sanitizer.warnings()


def _build_response(udf_bytes: bytes, filename: str, paragraph_count: int,
                    output_path: str | None, warnings: list[str]) -> dict[str, Any]:
    resp: dict[str, Any] = {
        "filename": filename,
        "size_bytes": len(udf_bytes),
        "paragraph_count": paragraph_count,
    }
    if output_path:
        path = os.path.expanduser(output_path)
        with open(path, "wb") as f:
            f.write(udf_bytes)
        resp["written_to"] = path
    else:
        resp["content_base64"] = base64.b64encode(udf_bytes).decode("ascii")
        resp["instructions"] = (
            "content_base64 alanını decode edip .udf dosyası olarak kaydedin. "
            "macOS Terminal: echo '<base64>' | base64 -d > "
            f"~/Desktop/{filename}"
        )
    if warnings:
        resp["warnings"] = warnings
    return resp


_NOT_UDF_SIGNATURES = (
    (b"%PDF", "PDF"),
    (b"II*\x00", "TIFF"),
    (b"MM\x00*", "TIFF"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG", "PNG"),
)


def _read_document(data: bytes) -> UdfDocument:
    for signature, kind in _NOT_UDF_SIGNATURES:
        if data.startswith(signature):
            raise ToolError(f"Bu dosya gerçek bir UDF değil; içeriği {kind}. Dosyayı {kind} olarak açın.")
    try:
        return read_udf_document(data)
    except zipfile.BadZipFile:
        raise ToolError("Geçerli bir UDF değil: ZIP arşivi açılamadı.")
    except ValueError as e:
        raise ToolError(str(e))


def _read_response(doc: UdfDocument, include_formatting: bool) -> dict[str, Any]:
    paras = doc.paragraphs
    resp: dict[str, Any] = {
        "paragraph_count": len(paras),
        "plain_text": document_text(doc),
    }
    if doc.verification_code:
        resp["verification_code"] = doc.verification_code
    if include_formatting:
        resp["paragraphs"] = paragraphs_to_dict(paras)
    return resp


def _native_pdf(convert, *args) -> str:
    from java_bridge import NativeConversionError
    try:
        return convert(*args)
    except NativeConversionError as e:
        raise ToolError(str(e))


# ----------------------------------------------------------------------------
# MCP tools
# ----------------------------------------------------------------------------

@mcp.tool()
def create_udf_from_markdown(
    markdown: str,
    filename: str = "dilekce.udf",
    output_path: str | None = None,
) -> dict[str, Any]:
    """Markdown benzeri metinden UYAP Doküman Editörü (.udf) dilekçesi üretir.

    Her satır bir paragraftır. Boş satırlar yok sayılır; boşluk gerekiyorsa <br> yazın.
    Satır içi: **kalın**, *italik*, ***kalın italik***, __altı çizili__. Künyede hizalama için TAB (\\t).
    İlk bölüm başlığından önceki "ETİKET\\t\\t: değer" ve "\\t\\t  değer" satırlarına asılı girinti
    verilir: değer alt satıra taşarsa sol kenardan değil, iki nokta sütununun hizasından devam eder.

    Satır başı işaretleri:
      @|metin   → üst bilgi (antet): ortalı, her sayfada tekrarlanır; "@|<br>" antetten sonra boş satır
      #|metin   → mahkeme başlığı: ortalı, 14 punto ("#metin": 14 punto, iki yana yaslı)
      |metin    → ortalı ("Gönderilmek Üzere" gibi), sıkı satır aralığı
      ||metin   → sağa yaslı (imza bloğu), sıkı satır aralığı
      >>>metin  → içtihat alıntısı: sol girinti
      :::metin  → 150 pt sol girinti
      <br>      → bir satırlık boşluk

    Numaralandırma: "AÇIKLAMALAR :", "İTİRAZ NEDENLERİ :", "SONUÇ VE İSTEM :", "DELİLLER :",
    "HUKUKİ NEDENLER :", "EKLER :" gibi bölüm başlıklarından sonra "1. ..." ile başlayan satırlar
    UYAP'ın otomatik listesine çevrilir. Her bölümde numara 1'den başlar ve yazılan rakamın yerine
    UYAP'ın numarası görünür. Bölüm başlığı, büyük harfle yazılmış kısa bir etikettir; gövdedeki
    "Sonuç olarak", "Ekte sunulan" gibi cümleler numaralandırmayı sıfırlamaz. Numaralı maddeden
    sonraki düz paragraflar maddenin hizasında girintilenir. Dışarıdan gelen metinlerdeki Roma
    rakamlı (I., II.) maddeler ana liste, altlarındaki 1., 2. alt liste olur.

    UYAP Doküman Editörü emoji açamaz: emojiler "[emoji]" ile değiştirilir ve "warnings" alanında
    bildirilir; görünmez kontrol karakterleri boşluğa çevrilir.

    Args:
        markdown: UDF'e çevrilecek metin.
        filename: Çıktı dosyasının adı (claude.ai'da indirme için).
        output_path: Verilirse dosya buraya yazılır ve yanıtta base64 dönmez (yerel kullanım).

    Returns:
        {"filename", "size_bytes", "paragraph_count",
         "written_to" (output_path verildiyse) veya "content_base64" + "instructions",
         "warnings" (varsa)}
    """
    paras = _markdown_to_paragraphs(markdown)
    udf_bytes, warnings = _paragraphs_to_udf(paras)
    return _build_response(udf_bytes, filename, len(paras), output_path, warnings)


@mcp.tool()
def create_udf(
    paragraphs: list[dict[str, Any]],
    filename: str = "dilekce.udf",
    output_path: str | None = None,
) -> dict[str, Any]:
    """Yapılandırılmış paragraf listesinden .udf üretir (ince kontrol için).

    Her paragraf:
        {
          "alignment": "left" | "center" | "right" | "justify",
          "left_indent": 27.777779, "right_indent": ..., "first_line_indent": ...,  # opsiyonel (pt)
          "hanging": 151.0,                     # opsiyonel asılı girinti (pt): 2. satırdan itibaren
          "space_below": 8.503938, "space_above": 0.0,                               # opsiyonel (pt)
          "numbered": true, "number_type": "NUMBER_TYPE_NUMBER_DOT",
          "list_id": 1, "list_level": 1,                                             # opsiyonel liste
          "is_header": false, "is_footer": false,                                    # üst/alt bilgi
          "runs": [
            {"text": "...", "bold": true, "italic": false, "underline": false,
             "size": 12, "color": null, "family": "Times New Roman"}
          ]
        }
    Kısayol: "runs" yerine "text" verilebilir (formatsız tek run).
    read_udf(include_formatting=True) çıktısındaki "paragraphs" aynı şemadadır.

    Args:
        paragraphs: Yukarıdaki şemada paragraf listesi.
        filename: Çıktı dosya adı.
        output_path: Verilirse dosya buraya yazılır ve yanıtta base64 dönmez.

    Returns: create_udf_from_markdown ile aynı yapı.
    """
    paras = paragraphs_from_dict(paragraphs)
    udf_bytes, warnings = _paragraphs_to_udf(paras)
    return _build_response(udf_bytes, filename, len(paras), output_path, warnings)


@mcp.tool()
def read_udf_from_base64(content_base64: str, include_formatting: bool = False) -> dict[str, Any]:
    """Base64 olarak verilen bir .udf'i okur.

    Kullanıcı mevcut bir UDF'i düzenletmek istediğinde (örn. dosyayı chat'e attığında) önce bu
    tool'la include_formatting=True ile oku, sonra değiştir, sonra create_udf ile yeniden üret.

    Args:
        content_base64: .udf dosyasının base64 hali.
        include_formatting: True ise paragrafların biçimi de döner (create_udf şeması).

    Returns: read_udf ile aynı yapı.
    """
    try:
        data = base64.b64decode(content_base64, validate=False)
    except ValueError:
        raise ToolError("content_base64 çözülemedi.")
    return _read_response(_read_document(data), include_formatting)


@mcp.tool()
def read_udf(path: str, include_formatting: bool = False) -> dict[str, Any]:
    """Yerel diskteki bir .udf dosyasını okur (karar, iddianame, tutanak, dilekçe).

    Varsayılan olarak yalnızca metni döndürür: üst bilgi, gövde (iç içe tablolar dahil) ve alt bilgi
    belge sırasıyla; tablo satırlarında hücreler " | " ile ayrılır, resimler [resim] olarak geçer.
    Mevcut bir UDF'i biçimiyle düzenleyip create_udf ile yeniden üretmek gerekiyorsa
    include_formatting=True verin; paragraf/run listesi de döner (tablolar düz paragraf olur).
    Cloud deploy'da çalışmaz (server diske erişemez); read_udf_from_base64 kullanın.

    Args:
        path: .udf dosyasının yolu.
        include_formatting: True ise paragrafların biçimi de döner (create_udf şeması).

    Returns:
        {"paragraph_count", "plain_text",
         "verification_code" (UYAP doğrulama kodu, varsa), "paragraphs" (include_formatting ise)}
    """
    path = os.path.expanduser(path)
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise ToolError(f"Dosya okunamadı: {e}")
    return _read_response(_read_document(data), include_formatting)


@mcp.tool()
def convert_udf_to_pdf(udf_path: str, output_path: str | None = None) -> str:
    """Yerel bir .udf dosyasını resmi UYAP Doküman Editörü (Havelsan) motoruyla PDF'e çevirir.

    Mizanpaj UYAP'ınkiyle birebir aynıdır. Belgenin UYAP doğrulama kodu varsa her sayfanın sağ
    altına belgenin kendi karekodu (evrakdogrula.uyap.gov.tr) basılır. Resmi motor çalışmazsa
    başka motora geçilmez, hata döner.

    Args:
        udf_path: .udf dosyasının mutlak yolu.
        output_path: İsteğe bağlı .pdf çıktı yolu. Verilmezse udf_path'in sonu .pdf yapılır.
    """
    from pdf_converter import convert_udf_file_to_pdf
    res_path = _native_pdf(convert_udf_file_to_pdf, os.path.expanduser(udf_path), output_path)
    return f"UDF resmi UYAP motoruyla PDF'e dönüştürüldü: {res_path}"


@mcp.tool()
def convert_markdown_to_pdf(markdown: str, output_path: str) -> str:
    """Markdown metnini (create_udf_from_markdown sözdizimi) UDF'e çevirip resmi UYAP motoruyla PDF yapar.

    PDF, aynı metinden üretilen .udf'in UYAP'taki görünümüyle birebir aynıdır.

    Args:
        markdown: Dönüştürülecek markdown metni.
        output_path: .pdf dosyasının mutlak kaydedileceği yol.
    """
    from pdf_converter import convert_udf_bytes_to_pdf
    udf_bytes, warnings = _paragraphs_to_udf(_markdown_to_paragraphs(markdown))
    res_path = _native_pdf(convert_udf_bytes_to_pdf, udf_bytes, os.path.expanduser(output_path))
    message = f"Markdown resmi UYAP motoruyla PDF'e dönüştürüldü: {res_path}"
    if warnings:
        message += "\nUyarılar: " + " ".join(warnings)
    return message


# ----------------------------------------------------------------------------
# Entrypoint
# ----------------------------------------------------------------------------

def main():
    use_http = "--http" in sys.argv or os.getenv("MCP_TRANSPORT") == "http"
    if use_http:
        port = int(os.getenv("PORT", "8000"))
        host = os.getenv("HOST", "0.0.0.0")
        mcp.run(transport="http", host=host, port=port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
