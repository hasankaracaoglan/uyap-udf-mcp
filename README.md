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

## Yapay zekâ asistanıyla kurulum

Terminal kullanabilen bir yapay zekâ asistanına (Claude Code, Antigravity vb.) bu sayfanın bağlantısını
verip “bunu kur” demeniz yeterlidir. Asistan aşağıdaki adımları izler; komut çalıştırmadan önce izin ister.

**Asistan için adımlar:**

Bu sunucuyu dilekçe becerileriyle birlikte kuruyorsan [AvukatLab paketinin kurulum talimatını](https://github.com/hasankaracaoglan/avukatlab-yapay-zeka/blob/main/KURULUM.md) izle; üç sunucuyu ve becerileri birlikte kurar.

Sunucu bilgisayara kalıcı olarak kurulur; açılırken internete, GitHub'a ya da git'e ihtiyaç duymaz.

1. `uv`'nin tam yolunu bul: `command -v uv` boş dönerse `~/.local/bin/uv`, `/opt/homebrew/bin/uv` ve `/usr/local/bin/uv`
   yollarını da dene. Yalnızca hiçbirinde yoksa kur. macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
   Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
2. Sunucuyu kur (zaman aşımı en az 10 dakika olsun; "operation timed out" ile yarıda kalırsa bir kez daha çalıştır):
   `UV_HTTP_TIMEOUT=180 <uv> tool install https://github.com/hasankaracaoglan/uyap-udf-mcp/archive/refs/heads/main.zip`
3. Komutun tam yolu `<uv> tool dir --bin` klasöründeki `uyap-udf-mcp` dosyasıdır (çoğunlukla `~/.local/bin/uyap-udf-mcp`; ayarlara
   açık yolu yaz). Masaüstü uygulamaları `~/.local/bin`'i PATH'te görmez. Bu yolu kullanıcının asistanına ekle:
   - **Claude Code:** `claude mcp add uyap-udf-mcp -s user -- <tam yol>`
   - **Claude Desktop:** `~/Library/Application Support/Claude/claude_desktop_config.json`
     (Windows: `%APPDATA%\Claude\claude_desktop_config.json`). Dosya yoksa oluştur.
   - **Antigravity:** `~/.gemini/config/mcp_config.json` (yeni sürüm) ya da `~/.gemini/antigravity/mcp_config.json`.
   - JSON dosyalarında önce yedek al, sonra `mcpServers` nesnesine `"uyap-udf-mcp": {"command": "<tam yol>", "args": []}`
     girdisini ekle. Var olan diğer sunuculara ve anahtarlara dokunma, dosyanın geçerli JSON kaldığını doğrula.
     Aynı adla eski bir girdi varsa (ör. eskiden kurulmuş `uvx uyap-udf-mcp`) kullanıcıya göster, yedekle ve değiştirmek
     için izin al. Sunucunun kendisini terminalde çalıştırma; girdi bekleyip açık kalır.
4. PDF dönüştürme için Uyap Doküman Editörü'nün macOS'ta `/Applications` altında kurulu olması gerekir;
   ayrıca Java kurmak gerekmez. UDF üretme ve okuma için gerekmez.
5. Kullanıcıya asistan uygulamasını tamamen kapatıp yeniden açmasını söyle.

Güncelleme kendiliğinden olmaz. Güncellemek için: `UV_HTTP_TIMEOUT=180 <uv> tool install --reinstall --refresh https://github.com/hasankaracaoglan/uyap-udf-mcp/archive/refs/heads/main.zip`,
ardından asistan uygulamasını yeniden başlat. Kaldırmak için: `<uv> tool uninstall uyap-udf-mcp` ve ayardaki girdiyi sil.

## Elle kurulum

Python 3.10 veya üstü gerekir (uv gerekirse kendisi indirir). Önce [uv](https://docs.astral.sh/uv/)'yi kurun (Terminal'de `curl -LsSf https://astral.sh/uv/install.sh | sh`), sonra sunucuyu kalıcı olarak kurun:

```bash
~/.local/bin/uv tool install https://github.com/hasankaracaoglan/uyap-udf-mcp/archive/refs/heads/main.zip
```

MCP istemcisinde komut olarak kurulan dosyanın tam yolunu yazın (Terminal'de `echo $HOME` ile kendi yolunuzu öğrenin), örneğin Claude Desktop'ta `claude_desktop_config.json`:

```json
{"mcpServers": {"uyap-udf-mcp": {"command": "/Users/KULLANICI/.local/bin/uyap-udf-mcp", "args": []}}}
```

Güncellemek için `~/.local/bin/uv tool install --reinstall --refresh https://github.com/hasankaracaoglan/uyap-udf-mcp/archive/refs/heads/main.zip` çalıştırıp istemciyi yeniden başlatın.

Kaynaktan geliştirmek için:

```bash
git clone https://github.com/hasankaracaoglan/uyap-udf-mcp.git
cd uyap-udf-mcp && python3 -m venv .venv && .venv/bin/pip install -e .
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
