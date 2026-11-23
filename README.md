# UYAP UDF MCP

Claude ve diğer MCP istemcilerinin UYAP Doküman Editörü biçiminde (`.udf`) dilekçe üretmesini,
`.udf` dosyalarını okumasını ve bunları resmi UYAP motoruyla PDF'e çevirmesini sağlayan MCP sunucusu.

> Bu proje [johanfaberrr/uyap-udf-mcp](https://github.com/johanfaberrr/uyap-udf-mcp) projesinden
> geliştirilmiştir (MIT). Asıl projede `.udf` üretme ve okuma vardı. Bu sürümde eklenenler:
> resmi UYAP motoruyla PDF dönüştürme, belgeye özgü doğrulama karekodu, UYAP'ın otomatik madde
> numaralandırması, antet (üst bilgi), künyede asılı girinti, iç içe kalın/italik, iç içe tablo,
> resim ve altbilgi okuma, macOS Finder hızlı eylemi.
>
> UYAP, Adalet Bakanlığı'nın; UYAP Doküman Editörü Havelsan'ın ürünüdür. Bu proje onlarla bağlantılı
> değildir, onlar tarafından desteklenmez ve editörün hiçbir dosyasını içermez.

## Araçlar

| Araç | Ne yapar |
|---|---|
| `create_udf_from_markdown` | Markdown benzeri metinden `.udf` üretir (önerilen) |
| `create_udf` | Yapılandırılmış paragraf listesinden `.udf` üretir (ayrıntılı denetim) |
| `read_udf` | Yerel bir `.udf` dosyasının metnini (istenirse biçimiyle) okur |
| `read_udf_from_base64` | base64 olarak verilen `.udf`'i okur |
| `convert_udf_to_pdf` | `.udf`'i resmi UYAP Doküman Editörü motoruyla PDF'e çevirir |
| `convert_markdown_to_pdf` | Markdown → `.udf` → resmi motorla PDF |

`.udf` üretme ve okuma saf Python'dur, her işletim sisteminde çalışır.

PDF dönüştürme bilgisayarda kurulu UYAP Doküman Editörü'nün kendi PDF motorunu kullanır, bu yüzden
mizanpaj UYAP'taki görünümle birebir aynıdır. Resmi motor çalışmazsa başka bir motora geçilmez,
hata döner.

## Kurulum

Python 3.10 veya üstü ve [uv](https://docs.astral.sh/uv/) gerekir. En kolay yol, MCP istemcisinin
sunucuyu doğrudan GitHub'dan çalıştırmasıdır (Claude Desktop'ta `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "uyap-udf-mcp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/hasankaracaoglan/uyap-udf-mcp", "uyap-udf-mcp"]
    }
  }
}
```

Claude Desktop `uvx`'i bulamazsa `command` alanına tam yolunu yazın (Terminal'de `which uvx`, çoğunlukla `/Users/<kullanıcı>/.local/bin/uvx`).

Kaynaktan kurmak için:

```bash
git clone https://github.com/hasankaracaoglan/uyap-udf-mcp.git
cd uyap-udf-mcp
python3 -m venv .venv
.venv/bin/pip install -e .
```

Bu durumda komut `/tam/yol/uyap-udf-mcp/.venv/bin/uyap-udf-mcp` olur.

HTTP olarak çalıştırmak için `python server.py --http` kullanılır (`PORT`, varsayılan 8000). HTTP
kipinde dosyalar diske yazılmaz, base64 olarak döner.

### PDF dönüştürme için ek gereksinimler

- **macOS** üzerinde `/Applications` altında kurulu **UYAP Doküman Editörü**.
- Dönüştürücü betiği (`uyap_native_converter.js`) editörün kendi jar dosyaları üzerinde Java 8'in `jjs`
  aracıyla çalışır. Sistemde çalışan bir Java 8 varsa o, yoksa editörün içindeki gömülü Java 8
  (`zulu-8.jre`) kullanılır; ayrıca Java kurmak gerekmez.

Windows ve Linux'ta PDF dönüştürme şimdilik desteklenmiyor: editörün kurulum klasörü yalnızca
macOS'ta aranıyor.

`install_mac_quick_action.sh`, Finder'a "UDF'yi PDF'e Çevir" sağ tık eylemini kurar.

## Markdown sözdizimi (`create_udf_from_markdown`)

Her satır bir paragraftır. Boş satırlar yok sayılır, boşluk gerekiyorsa `<br>` yazılır.

- Satır içi: `**kalın**`, `*italik*`, `***kalın italik***`, `__altı çizili__`. İç içe de yazılabilir:
  `*"...karar metni **vurgulanan kısım** karar metni..."*`.
- `@|metin`: üst bilgi (antet), ortalı, her sayfada tekrarlanır.
- `#|metin`: mahkeme başlığı, ortalı, 14 punto.
- `|metin`: ortalı.
- `||metin`: sağa yaslı (imza bloğu).
- `>>>metin`: içtihat alıntısı, sol girinti.
- `:::metin`: 150 pt sol girinti.
- `<br>`: bir satırlık boşluk.
- Künyede hizalama için TAB (`\t`): `**DOSYA NO\t\t:** 2026/123 Esas`.
- `AÇIKLAMALAR :`, `SONUÇ VE İSTEM :` gibi bölüm başlıklarından sonra `1. ...` ile başlayan satırlar
  UYAP'ın otomatik listesine çevrilir.

Örnek:

```
#|**İZMİR NÖBETÇİ ASLİYE HUKUK MAHKEMESİNE**
<br>
**DAVACI\t\t:** Ali VELİ
**KONU\t\t:** ...

**AÇIKLAMALAR :**

1. Açıklama metni...

**SONUÇ VE İSTEM :** Yukarıda açıklanan nedenlerle;

1. Davanın kabulüne karar verilmesini saygıyla talep ederim.

||**Av. Ad SOYAD**
```

## Lisans

MIT. Bkz. [LICENSE](LICENSE).
