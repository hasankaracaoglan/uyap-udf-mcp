"""UDF (UYAP Doküman Formatı) reader/writer & document model.

UDF = ZIP arşivi: content.xml (zorunlu), documentproperties.xml (doğrulama kodu) ve sign.sgn (e-imza).
content.xml'de tüm metin tek bir CDATA'dadır; paragraflardaki content/field/space/tab/image
öğeleri bu metne startOffset/length ile işaret eder.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

# Alignment kodları (UYAP konvansiyonu)
ALIGN_LEFT = 0
ALIGN_CENTER = 1
ALIGN_RIGHT = 2
ALIGN_JUSTIFY = 3

ALIGN_MAP = {
    "left": ALIGN_LEFT,
    "center": ALIGN_CENTER,
    "right": ALIGN_RIGHT,
    "justify": ALIGN_JUSTIFY,
    "sola": ALIGN_LEFT,
    "ortala": ALIGN_CENTER,
    "saga": ALIGN_RIGHT,
    "iki yana": ALIGN_JUSTIFY,
}

INLINE_TAGS = ("content", "field", "space", "tab", "image")
IMAGE_PLACEHOLDER = "[resim]"


@dataclass
class PageFormat:
    left_margin: float = 42.519685
    right_margin: float = 42.519685
    top_margin: float = 42.519685
    bottom_margin: float = 42.519685
    paper_orientation: int = 1  # 1: Portrait, 2: Landscape
    media_size_name: str = "1"


@dataclass
class Run:
    """Tek bir formatlama dilimi (bir paragraf içinde)."""
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    size: int | None = None
    color: str | None = None
    family: str | None = None


@dataclass
class Paragraph:
    runs: list[Run] = field(default_factory=list)
    alignment: int = ALIGN_JUSTIFY  # default: iki yana yaslı
    left_indent: float | None = None
    right_indent: float | None = None
    first_line_indent: float | None = None
    hanging: float | None = None  # asılı girinti: ilk satırdan sonraki satırlar LeftIndent + hanging'den başlar
    space_below: float | None = 6.0
    space_above: float | None = 0.0
    numbered: bool = False
    number_type: str | None = None
    list_level: int | None = None
    list_id: int | None = None
    is_header: bool = False
    is_footer: bool = False
    list_label: str | None = None  # okurken UYAP'ın çizeceği madde numarası ("1.", "a.", "●"); yazılmaz

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


class ListNumbering:
    """UYAP'ın liste numaraları: ListId ve seviye başına sayaç, Türk alfabesiyle harfler,
    SecListTypeLevelN verilmemişse seviyeye göre varsayılan tür (UDFQuickLook ile aynı kurallar)."""

    NUMBER_DEFAULTS = ["NUMBER_TYPE_NUMBER_DOT", "NUMBER_TYPE_CHAR_SMALL_DOT", "NUMBER_TYPE_ROMAN_SMALL_DOT",
                       "PAREN_NUMBER", "PAREN_CHAR_SMALL", "PAREN_ROMAN_SMALL"]
    BULLET_DEFAULTS = ["BULLET_TYPE_ELLIPSE", "BULLET_TYPE_RECTANGLE", "BULLET_TYPE_RECTANGLE_D"]
    UPPER = "ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ"
    LOWER = "abcçdefgğhıijklmnoöprsştuüvyz"

    def __init__(self) -> None:
        self.counters: dict[str, list[int]] = {}

    def marker(self, attrs: dict[str, str]) -> str | None:
        """attrs: paragrafın XML öznitelikleri, anahtarlar küçük harfle."""
        numbered = attrs.get("numbered") == "true"
        bulleted = attrs.get("bulleted") == "true"
        if not (numbered or bulleted):
            return None
        try:
            level = max(1, int(attrs.get("listlevel", "1")))
        except ValueError:
            level = 1
        levels = self.counters.get(attrs.get("listid", ""), [])
        if len(levels) < level:
            levels = levels + [0] * (level - len(levels))
        else:
            levels = levels[:level]  # üst madde alt seviyeleri yeniden başlatır
        if attrs.get("numbersetted", "").isdigit():
            levels[level - 1] = int(attrs["numbersetted"])
        levels[level - 1] += 1
        self.counters[attrs.get("listid", "")] = levels

        if f"seclisttypelevel{level}" in attrs:
            kind = attrs[f"seclisttypelevel{level}"]
        elif level == 1:
            kind = attrs.get("numbertype" if numbered else "bullettype") or (
                "NUMBER_TYPE_NUMBER_DOT" if numbered else "BULLET_TYPE_ELLIPSE")
        else:
            defaults = self.NUMBER_DEFAULTS if numbered else self.BULLET_DEFAULTS
            kind = defaults[(level - 1) % len(defaults)]
        return self._label(kind.upper(), levels[level - 1])

    @classmethod
    def _label(cls, t: str, n: int) -> str:
        if t.startswith("BULLET"):
            for key, mark in (("RECTANGLE_D", "▫"), ("RECTANGLE", "▪"), ("ARROW", "➤"),
                              ("DIAMOND", "◆"), ("TRIANGLE", "►")):
                if key in t:
                    return mark
            return "●"
        if "ROMAN_BIG" in t:
            core = cls._roman(n)
        elif "ROMAN" in t:
            core = cls._roman(n).lower()
        elif "CHAR_BIG" in t:
            core = cls._letters(n, cls.UPPER)
        elif "CHAR" in t:
            core = cls._letters(n, cls.LOWER)
        else:
            core = str(n)
        if t.startswith("PAREN_"):
            return f"({core})"
        if "PARANTHESE" in t:
            return f"{core})"
        if "TRE" in t:
            return f"{core}-"
        return f"{core}."

    @staticmethod
    def _letters(n: int, alphabet: str) -> str:
        value, result = max(1, n), ""
        while value > 0:
            value -= 1
            result = alphabet[value % len(alphabet)] + result
            value //= len(alphabet)
        return result

    @staticmethod
    def _roman(n: int) -> str:
        if not 0 < n < 4000:
            return str(n)
        result = ""
        for amount, symbol in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                               (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
            while n >= amount:
                result += symbol
                n -= amount
        return result


@dataclass
class Cell:
    elements: list[Paragraph | Table] = field(default_factory=list)
    width: float | None = None
    background: str | None = None


@dataclass
class Row:
    cells: list[Cell] = field(default_factory=list)


@dataclass
class Table:
    rows: list[Row] = field(default_factory=list)
    border: str = "borderNone"


@dataclass
class UdfDocument:
    page_format: PageFormat = field(default_factory=PageFormat)
    header: list[Paragraph | Table] = field(default_factory=list)
    elements: list[Paragraph | Table] = field(default_factory=list)
    footer: list[Paragraph | Table] = field(default_factory=list)
    verification_code: str = ""

    @property
    def paragraphs(self) -> list[Paragraph]:
        """Üst bilgi ve gövdedeki tüm paragraflar (tablo hücreleri dahil), belge sırasıyla."""
        return _flatten(self.header) + _flatten(self.elements)


def _flatten(elements: list[Paragraph | Table]) -> list[Paragraph]:
    result: list[Paragraph] = []
    for elem in elements:
        if isinstance(elem, Paragraph):
            result.append(elem)
        else:
            for row in elem.rows:
                for cell in row.cells:
                    result.extend(_flatten(cell.elements))
    return result


# ----------------------------------------------------------------------------
# UDF Okuma
# ----------------------------------------------------------------------------

def _float_attr(node: ET.Element, name: str) -> float | None:
    value = node.get(name)
    return float(value) if value not in (None, "") else None


def read_udf_document(source: str | bytes) -> UdfDocument:
    """UDF'i (dosya yolu ya da ham bayt) yapısal UdfDocument modeli olarak okur."""
    if isinstance(source, bytes):
        data = source
    else:
        with open(source, "rb") as f:
            data = f.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        if "content.xml" not in zf.namelist():
            raise ValueError("Geçerli bir UDF değil: content.xml yok")
        xml_text = zf.read("content.xml").decode("utf-8-sig")
        ver_code = ""
        if "documentproperties.xml" in zf.namelist():
            dp_xml = zf.read("documentproperties.xml").decode("utf-8", "replace")
            m_code = re.search(r'<entry key="uyapdogrulamakodu">(.*?)</entry>', dp_xml)
            if m_code:
                ver_code = m_code.group(1).strip()

    # Offset'ler ham CDATA'ya göredir; XML ayrıştırıcısı satır sonlarını değiştirebileceği için regex ile alınır.
    m = re.search(r"<content><!\[CDATA\[(.*?)\]\]></content>", xml_text, re.DOTALL)
    if not m:
        raise ValueError("content.xml içinde CDATA bulunamadı")
    full_text = m.group(1)

    root = ET.fromstring(xml_text)

    pf = PageFormat()
    pf_node = root.find("properties/pageFormat")
    if pf_node is not None:
        pf.left_margin = float(pf_node.get("leftMargin", pf.left_margin))
        pf.right_margin = float(pf_node.get("rightMargin", pf.right_margin))
        pf.top_margin = float(pf_node.get("topMargin", pf.top_margin))
        pf.bottom_margin = float(pf_node.get("bottomMargin", pf.bottom_margin))
        pf.paper_orientation = int(pf_node.get("paperOrientation", "1"))
        pf.media_size_name = pf_node.get("mediaSizeName", "1")

    elements_node = root.find("elements")
    if elements_node is None:
        raise ValueError("elements bulunamadı")

    numbering = ListNumbering()

    def parse_para(node: ET.Element, is_hdr: bool, is_ftr: bool) -> Paragraph:
        runs: list[Run] = []
        for c in node:
            if c.tag not in INLINE_TAGS:
                continue
            if c.tag == "image":
                text = IMAGE_PLACEHOLDER
            else:
                so = int(c.get("startOffset", "0"))
                text = full_text[so : so + int(c.get("length", "0"))]
            size = c.get("size")
            runs.append(
                Run(
                    text=text,
                    bold=c.get("bold") == "true",
                    italic=c.get("italic") == "true",
                    underline=c.get("underline") == "true",
                    size=int(float(size)) if size else 12,
                    family=c.get("family", "Times New Roman"),
                    color=c.get("color"),
                )
            )
        list_level = node.get("ListLevel")
        list_id = node.get("ListId")
        space_below = _float_attr(node, "SpaceBelow")
        space_above = _float_attr(node, "SpaceAbove")
        return Paragraph(
            runs=runs,
            alignment=int(node.get("Alignment", "3")),
            left_indent=_float_attr(node, "LeftIndent"),
            right_indent=_float_attr(node, "RightIndent"),
            first_line_indent=_float_attr(node, "FirstLineIndent"),
            hanging=_float_attr(node, "Hanging"),
            space_below=space_below if space_below is not None else 6.0,
            space_above=space_above if space_above is not None else 0.0,
            numbered=node.get("Numbered") == "true",
            number_type=node.get("NumberType"),
            list_level=int(list_level) if list_level else None,
            list_id=int(list_id) if list_id else None,
            is_header=is_hdr,
            is_footer=is_ftr,
            list_label=numbering.marker({k.lower(): v for k, v in node.attrib.items()}),
        )

    def parse_block(container: ET.Element, is_hdr: bool = False, is_ftr: bool = False) -> list[Paragraph | Table]:
        """Paragrafları ve (iç içe) tabloları belge sırasıyla okur."""
        result: list[Paragraph | Table] = []
        for node in container:
            if node.tag == "paragraph":
                result.append(parse_para(node, is_hdr, is_ftr))
            elif node.tag == "table":
                tbl = Table(border=node.get("border", "borderNone"))
                for row_node in node.findall("row"):
                    row = Row()
                    for cell_node in row_node.findall("cell"):
                        row.cells.append(Cell(
                            elements=parse_block(cell_node, is_hdr, is_ftr),
                            width=_float_attr(cell_node, "width"),
                            background=cell_node.get("background"),
                        ))
                    tbl.rows.append(row)
                result.append(tbl)
        return result

    doc = UdfDocument(page_format=pf, verification_code=ver_code)
    for node in elements_node:
        if node.tag == "header":
            doc.header.extend(parse_block(node, is_hdr=True))
        elif node.tag == "footer":
            doc.footer.extend(parse_block(node, is_ftr=True))
        else:
            doc.elements.extend(parse_block([node]))
    return doc


def read_udf(source: str | bytes) -> list[Paragraph]:
    return read_udf_document(source).paragraphs


def _line(p: Paragraph) -> str:
    # Paragraf içindeki "\n" UYAP'ta çizilmez; yalnızca paragraf sonu satır kırar.
    text = re.sub(r"\t+", "\t", p.text.replace("\n", "")).rstrip()
    return f"{p.list_label} {text.lstrip()}" if p.list_label and text.strip() else text


def _render(elements: list[Paragraph | Table], out: list[str]) -> None:
    for elem in elements:
        if isinstance(elem, Paragraph):
            out.append(_line(elem))
            continue
        for row in elem.rows:
            if any(isinstance(e, Table) for cell in row.cells for e in cell.elements):
                for cell in row.cells:
                    _render(cell.elements, out)
                continue
            cells = []
            for cell in row.cells:
                text = " ".join(t.strip() for t in (_line(p) for p in cell.elements) if t.strip())
                if text:
                    cells.append(text)
            if cells:
                out.append(" | ".join(cells))


def document_text(doc: UdfDocument) -> str:
    """Belgenin okunur metni: üst bilgi, gövde ve alt bilgi; tablo satırlarında hücreler " | " ile ayrılır."""
    out: list[str] = []
    _render(doc.header, out)
    _render(doc.elements, out)
    _render(doc.footer, out)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def paragraphs_to_dict(paragraphs: list[Paragraph]) -> list[dict[str, Any]]:
    """create_udf'in beklediği şema; boş/varsayılan değerler yazılmaz."""
    align_map_rev = {
        ALIGN_LEFT: "left",
        ALIGN_CENTER: "center",
        ALIGN_RIGHT: "right",
        ALIGN_JUSTIFY: "justify",
    }
    result = []
    for p in paragraphs:
        d: dict[str, Any] = {"alignment": align_map_rev.get(p.alignment, "justify")}
        for key in ("left_indent", "right_indent", "first_line_indent", "hanging", "space_below", "space_above",
                    "numbered", "number_type", "list_level", "list_id", "is_header", "is_footer"):
            value = getattr(p, key)
            if value not in (None, False):
                d[key] = value
        runs = []
        for r in p.runs:
            rd: dict[str, Any] = {"text": r.text}
            if r.bold:
                rd["bold"] = True
            if r.italic:
                rd["italic"] = True
            if r.underline:
                rd["underline"] = True
            if r.size not in (None, 12):
                rd["size"] = r.size
            if r.color:
                rd["color"] = r.color
            if r.family not in (None, "Times New Roman"):
                rd["family"] = r.family
            runs.append(rd)
        d["runs"] = runs
        result.append(d)
    return result


def paragraphs_from_dict(paragraphs: list[dict[str, Any]]) -> list[Paragraph]:
    result = []
    for p in paragraphs:
        align_val = p.get("alignment", ALIGN_JUSTIFY)
        if isinstance(align_val, str):
            align = ALIGN_MAP.get(align_val.lower(), ALIGN_JUSTIFY)
        else:
            align = int(align_val)

        runs = []
        if "runs" in p and isinstance(p["runs"], list):
            for r in p["runs"]:
                runs.append(
                    Run(
                        text=str(r.get("text", "")),
                        bold=bool(r.get("bold", False)),
                        italic=bool(r.get("italic", False)),
                        underline=bool(r.get("underline", False)),
                        size=r.get("size"),
                        color=r.get("color"),
                        family=r.get("family"),
                    )
                )
        elif "text" in p:
            runs.append(Run(text=str(p["text"])))

        result.append(
            Paragraph(
                runs=runs,
                alignment=align,
                left_indent=p.get("left_indent"),
                right_indent=p.get("right_indent"),
                first_line_indent=p.get("first_line_indent"),
                hanging=p.get("hanging"),
                space_below=p.get("space_below", 6.0),
                space_above=p.get("space_above", 0.0),
                numbered=bool(p.get("numbered", False)),
                number_type=p.get("number_type"),
                list_level=p.get("list_level"),
                list_id=p.get("list_id"),
                is_header=bool(p.get("is_header", False)),
                is_footer=bool(p.get("is_footer", False)),
            )
        )
    return result


# ----------------------------------------------------------------------------
# UDF Yazma
# ----------------------------------------------------------------------------

# UYAP'ın XML kütüphanesi (eski JDOM) BMP dışı karakterleri (emoji) ve kontrol karakterlerini reddeder;
# böyle bir karakter içeren UDF Doküman Editörü'nde açılmaz. "\r" ise XML'de "\n"e dönüşüp offset'leri kaydırır.
_UNSAFE = re.compile("[\x00-\x08\x0b-\x1f￾￿\U00010000-\U0010ffff]|]]>")
EMOJI_PLACEHOLDER = "[emoji]"


class TextSanitizer:
    """Metni UYAP'ın açabileceği hale getirir ve yapılan değişiklikleri raporlar."""

    def __init__(self) -> None:
        self.emoji: list[str] = []
        self.styled: list[str] = []
        self.controls = 0

    def _replace(self, m: re.Match) -> str:
        ch = m.group(0)
        if ch == "]]>":
            return "]] >"
        if ch == "\r":
            return ""
        if ord(ch) > 0xFFFF:
            # Süslü yazı harfleri (𝐒𝐞𝐧𝐢 vb.) NFKC ile düz harfe döner; dönmeyenler emojidir.
            plain = unicodedata.normalize("NFKC", ch)
            if plain != ch and plain.strip() and all(ord(c) <= 0xFFFF for c in plain):
                self.styled.append(ch)
                return plain
            self.emoji.append(ch)
            return EMOJI_PLACEHOLDER
        self.controls += 1
        return " "

    def clean(self, text: str) -> str:
        return _UNSAFE.sub(self._replace, text) if _UNSAFE.search(text) else text

    def warnings(self) -> list[str]:
        result = []
        if self.emoji:
            sample = " ".join(dict.fromkeys(self.emoji))
            result.append(
                f"UYAP emojileri açamadığı için {len(self.emoji)} emoji '{EMOJI_PLACEHOLDER}' ile değiştirildi "
                f"({sample}). Gerekirse sözle anlatın, ör. '(kızgın yüz emojisi)'."
            )
        if self.styled:
            result.append(f"{len(self.styled)} süslü yazı karakteri (𝐀 gibi) düz harfe çevrildi.")
        if self.controls:
            result.append(f"{self.controls} görünmez kontrol karakteri (sayfa sonu vb.) boşlukla değiştirildi.")
        return result


def _attr(value: Any) -> str:
    return xml_escape(str(value), {'"': "&quot;"})


def build_content_xml(
    paragraphs: list[Paragraph],
    page_format: PageFormat | None = None,
    sanitizer: TextSanitizer | None = None,
) -> str:
    """Paragraph ve Run listesinden UYAP Doküman Editörü uyumlu content.xml metni üretir."""
    page_format = page_format or PageFormat()
    sanitizer = sanitizer or TextSanitizer()
    header_paras = [p for p in paragraphs if p.is_header]
    body_paras = [p for p in paragraphs if not p.is_header and not p.is_footer]
    footer_paras = [p for p in paragraphs if p.is_footer]

    current_offset = 0
    cdata_chunks: list[str] = []

    def format_para_node(p: Paragraph) -> str:
        nonlocal current_offset
        p_attrs = [f'Alignment="{p.alignment}"']
        if p.left_indent is not None:
            p_attrs.append(f'LeftIndent="{p.left_indent}"')
        if p.right_indent is not None:
            p_attrs.append(f'RightIndent="{p.right_indent}"')
        if p.first_line_indent is not None:
            p_attrs.append(f'FirstLineIndent="{p.first_line_indent}"')
        if p.hanging is not None:
            p_attrs.append(f'Hanging="{p.hanging}"')
        if p.space_below is not None:
            p_attrs.append(f'SpaceBelow="{p.space_below}"')
        if p.space_above is not None:
            p_attrs.append(f'SpaceAbove="{p.space_above}"')
        if p.numbered:
            p_attrs.append('Numbered="true"')
            if p.number_type:
                p_attrs.append(f'NumberType="{_attr(p.number_type)}"')
            if p.list_level is not None:
                p_attrs.append(f'ListLevel="{p.list_level}"')
            if p.list_id is not None:
                p_attrs.append(f'ListId="{p.list_id}"')

        content_tags = []
        runs = p.runs if p.runs else [Run(text="")]

        for i, r in enumerate(runs):
            txt = sanitizer.clean(r.text)
            if i == len(runs) - 1 and not txt.endswith("\n"):
                txt += "\n"

            length = len(txt)
            start = current_offset
            current_offset += length
            cdata_chunks.append(txt)

            c_attrs = [
                'name="hvl-default"',
                f'family="{_attr(r.family or "Times New Roman")}"',
                f'size="{r.size or 12}"',
            ]
            if r.bold:
                c_attrs.append('bold="true"')
            if r.italic:
                c_attrs.append('italic="true"')
            if r.underline:
                c_attrs.append('underline="true"')
            if r.color:
                c_attrs.append(f'color="{_attr(r.color)}"')

            c_attrs.append(f'startOffset="{start}"')
            c_attrs.append(f'length="{length}"')

            content_tags.append(f'<content {" ".join(c_attrs)} />')

        return f'<paragraph {" ".join(p_attrs)}>{"".join(content_tags)}</paragraph>'

    header_xml = ""
    if header_paras:
        h_snippets = [format_para_node(p) for p in header_paras]
        header_xml = f'<header>{"".join(h_snippets)}</header>'

    body_xml = "".join(format_para_node(p) for p in body_paras)

    footer_xml = ""
    if footer_paras:
        f_snippets = [format_para_node(p) for p in footer_paras]
        footer_xml = f'<footer>{"".join(f_snippets)}</footer>'
    else:
        cdata_chunks.append("\n  \n")
        f_start = current_offset
        current_offset += 4
        footer_xml = f'<footer pageNumber-spec="BSP32_72" color-boundary="-1" pageNumber-color="-16777216" pageNumber-fontFace="Arial" pageNumber-fontSize="11" pageNumber-foreStr="" pageNumber-pageStartNumStr=""><paragraph name="hvl-default" family="Times New Roman" size="12" description="Gövde"><content name="hvl-default" family="Times New Roman" size="12" description="Gövde" startOffset="{f_start}" length="3" /></paragraph></footer>'

    cdata_content = "".join(cdata_chunks)

    pf = page_format
    page_format_xml = (
        f'<pageFormat mediaSizeName="{pf.media_size_name}" '
        f'leftMargin="{pf.left_margin}" rightMargin="{pf.right_margin}" '
        f'topMargin="{pf.top_margin}" bottomMargin="{pf.bottom_margin}" '
        f'paperOrientation="{pf.paper_orientation}" headerFOffset="20.0" footerFOffset="20.0" />'
    )

    xml = (
        '<?xml version="1.0" encoding="UTF-8" ?> \n\n'
        '<template format_id="1.8" >\n'
        f'<content><![CDATA[{cdata_content}]]></content>'
        f'<properties>{page_format_xml}</properties>\n'
        f'<elements resolver="hvl-default" >{header_xml}{body_xml}{footer_xml}</elements>\n'
        '<styles><style name="default" description="Geçerli" family="Lucida Grande" size="13" bold="false" italic="false" FONT_ATTRIBUTE_KEY="com.apple.laf.AquaFonts$DerivedUIResourceFont[family=Lucida Grande,name=Lucida Grande,style=plain,size=13]" />'
        '<style name="hvl-default" family="Times New Roman" size="12" description="Gövde" /></styles>\n'
        '</template>\n'
    )
    return xml
