// UDF → PDF dönüştürücü: resmi UYAP Doküman Editörü (Havelsan) PDF motoru.
//
// Kullanım:
//   jjs -J-Djava.awt.headless=true -cp "<editörün tüm jar'ları>" uyap_native_converter.js -- in1.udf out1.pdf [in2.udf out2.pdf ...]
//
// Her çift için tek satır sonuç yazar (çift sırası 0'dan başlar):
//   UYAPCONV-OK<TAB><sıra>
//   UYAPCONV-ERR<TAB><sıra><TAB><neden>
// Bir çift bile başarısızsa çıkış kodu 1'dir. PDF önce aynı klasörde geçici dosyaya yazılır,
// başarılı olursa hedefin üzerine taşınır; hata olursa mevcut dosyaya dokunulmaz.
//
// Belgenin doğrulama kodu varsa (documentproperties.xml → uyapdogrulamakodu) her sayfanın sağ altına
// resmi UYAP karekodu basılır: https://evrakdogrula.uyap.gov.tr/<kod>, ZXing QR, hata düzeltme M, UTF-8,
// 51x51, konum (535, 1.89). UYAP'tan doğrudan inen PDF'lerdeki karekodla piksel piksel aynıdır.

var File = Java.type("java.io.File");
var FileOutputStream = Java.type("java.io.FileOutputStream");
var ByteArrayInputStream = Java.type("java.io.ByteArrayInputStream");
var ByteArrayOutputStream = Java.type("java.io.ByteArrayOutputStream");
var OutputStream = Java.type("java.io.OutputStream");
var JString = Java.type("java.lang.String");
var ZipFile = Java.type("java.util.zip.ZipFile");
var HashMap = Java.type("java.util.HashMap");
var Files = Java.type("java.nio.file.Files");
var StandardCopyOption = Java.type("java.nio.file.StandardCopyOption");
var BufferedImage = Java.type("java.awt.image.BufferedImage");
var ImageIO = Java.type("javax.imageio.ImageIO");

var QR_URL_PREFIX = "https://evrakdogrula.uyap.gov.tr/";
var QR_SIZE = 51;
var QR_X = 535;
var QR_Y = 1.89;

function emit(tag, index, reason) {
    var line = tag + "\t" + index;
    if (reason) {
        line += "\t" + String(reason).replace(/[\r\n\t]+/g, " ");
    }
    print(line);
}

function rootCauseMessage(e) {
    var t = e;
    if (t && t.getCause) {
        while (t.getCause() != null && t.getCause() !== t) {
            t = t.getCause();
        }
    }
    var msg = (t && t.getMessage) ? t.getMessage() : null;
    var name = (t && t.getClass) ? t.getClass().getSimpleName() : "Hata";
    var text = msg ? (name + ": " + msg) : String(t);
    // Havelsan'ın XML hataları belgenin tüm metnini içerir; asıl neden sondadır.
    if (text.length > 300) {
        text = name + ": ..." + text.substring(text.length - 200);
    }
    return text;
}

function readEntry(zf, name) {
    var entry = zf.getEntry(name);
    if (entry == null) {
        return null;
    }
    var is = zf.getInputStream(entry);
    try {
        var baos = new ByteArrayOutputStream();
        var buf = java.lang.reflect.Array.newInstance(java.lang.Byte.TYPE, 8192);
        var r;
        while ((r = is.read(buf)) > 0) {
            baos.write(buf, 0, r);
        }
        return baos.toByteArray();
    } finally {
        is.close();
    }
}

// The engine's old JDOM rejects emoji (surrogate pairs) and control characters and then fails with a
// bare NullPointerException; name the character instead.
function illegalXmlChar(text) {
    for (var i = 0; i < text.length; i++) {
        var c = text.charCodeAt(i);
        var cp = c;
        if (c >= 0xD800 && c <= 0xDBFF && i + 1 < text.length) {
            cp = ((c - 0xD800) << 10) + (text.charCodeAt(i + 1) - 0xDC00) + 0x10000;
        }
        if ((c < 0x20 && c != 0x09 && c != 0x0A && c != 0x0D) || (c >= 0xD800 && c <= 0xDFFF) || c == 0xFFFE || c == 0xFFFF) {
            var hex = cp.toString(16).toUpperCase();
            while (hex.length < 4) {
                hex = "0" + hex;
            }
            var before = text.substring(Math.max(0, i - 30), i).replace(/\s+/g, " ");
            return "U+" + hex + " (\"..." + before + "\" sonrasında)";
        }
    }
    return null;
}

function verificationQrImage(code) {
    var BarcodeFormat = Java.type("com.google.zxing.BarcodeFormat");
    var EncodeHintType = Java.type("com.google.zxing.EncodeHintType");
    var ErrorCorrectionLevel = Java.type("com.google.zxing.qrcode.decoder.ErrorCorrectionLevel");
    var QRCodeWriter = Java.type("com.google.zxing.qrcode.QRCodeWriter");
    var PdfImage = Java.type("com.lowagie.text.Image");

    var hints = new HashMap();
    hints.put(EncodeHintType.ERROR_CORRECTION, ErrorCorrectionLevel.M);
    hints.put(EncodeHintType.CHARACTER_SET, "UTF-8");
    var matrix = new QRCodeWriter().encode(QR_URL_PREFIX + code, BarcodeFormat.QR_CODE, QR_SIZE, QR_SIZE, hints);

    var w = matrix.getWidth(), h = matrix.getHeight();
    var img = new BufferedImage(w, h, BufferedImage.TYPE_INT_RGB);
    for (var y = 0; y < h; y++) {
        for (var x = 0; x < w; x++) {
            img.setRGB(x, y, matrix.get(x, y) ? 0x000000 : 0xFFFFFF);
        }
    }
    var png = new ByteArrayOutputStream();
    ImageIO.write(img, "png", png);

    var pdfImg = PdfImage.getInstance(png.toByteArray());
    pdfImg.scaleAbsolute(QR_SIZE, QR_SIZE);
    pdfImg.setAbsolutePosition(QR_X, QR_Y);
    pdfImg.setInterpolation(false);
    return pdfImg;
}

function findExportMethod() {
    var cls;
    try {
        cls = Java.type("tr.com.havelsan.uyap.system.editor.b.b");
    } catch (e) {
        return { error: "UYAP Doküman Editörü'nün PDF sınıfı bulunamadı (editör güncellenmiş olabilir): " + rootCauseMessage(e) };
    }
    var methods = cls.class.getDeclaredMethods();
    for (var i = 0; i < methods.length; i++) {
        var pTypes = methods[i].getParameterTypes();
        if (pTypes.length == 2 && pTypes[0] == OutputStream.class && pTypes[1] == ByteArrayInputStream.class) {
            methods[i].setAccessible(true);
            return { cls: cls, method: methods[i] };
        }
    }
    return { error: "UYAP Doküman Editörü'nün PDF metodu bulunamadı (editör güncellenmiş olabilir)." };
}

function convertOne(exporter, udfPath, pdfPath) {
    var PdfReader = Java.type("com.lowagie.text.pdf.PdfReader");
    var PdfStamper = Java.type("com.lowagie.text.pdf.PdfStamper");

    var udfFile = new File(udfPath);
    if (!udfFile.isFile()) {
        throw "UDF dosyası bulunamadı: " + udfPath;
    }

    var contentBytes, verCode = "";
    var zf = new ZipFile(udfFile);
    try {
        contentBytes = readEntry(zf, "content.xml");
        if (contentBytes == null) {
            throw "UDF içinde content.xml yok (geçerli bir UDF değil).";
        }
        var dpBytes = readEntry(zf, "documentproperties.xml");
        if (dpBytes != null) {
            var m = String(new JString(dpBytes, "UTF-8")).match(/<entry key="uyapdogrulamakodu">([^<]*)<\/entry>/);
            if (m) {
                verCode = m[1].trim();
            }
        }
    } finally {
        zf.close();
    }

    // 1. Havelsan motoruyla PDF'i belleğe üret
    var raw = new ByteArrayOutputStream();
    try {
        exporter.method.invoke(new exporter.cls(), raw, new ByteArrayInputStream(contentBytes));
    } catch (e) {
        var bad = illegalXmlChar(String(new JString(contentBytes, "UTF-8")));
        if (bad) {
            throw "Belgede UYAP'ın kabul etmediği bir karakter var: " + bad + ". Emoji ve görünmez kontrol karakterleri UYAP Doküman Editörü'nde açılmaz; çıkarılmalı.";
        }
        throw e;
    }
    var rawBytes = raw.toByteArray();
    if (rawBytes.length == 0) {
        throw "UYAP motoru boş PDF üretti.";
    }

    // 2. Doğrulama kodu varsa belgenin kendi karekodunu bas, geçici dosyaya yaz, sonra hedefe taşı
    var outFile = new File(pdfPath).getAbsoluteFile();
    var dir = outFile.getParentFile();
    if (dir == null || !dir.isDirectory()) {
        throw "PDF'in kaydedileceği klasör yok: " + (dir == null ? pdfPath : dir.getPath());
    }
    var tmpFile = File.createTempFile("." + outFile.getName() + ".", ".tmp", dir);
    try {
        var reader = new PdfReader(rawBytes);
        var out = new FileOutputStream(tmpFile);
        try {
            var stamper = new PdfStamper(reader, out);
            if (verCode) {
                var qr = verificationQrImage(verCode);
                var pages = reader.getNumberOfPages();
                for (var p = 1; p <= pages; p++) {
                    stamper.getOverContent(p).addImage(qr);
                }
            }
            stamper.close();
        } finally {
            out.close();
            reader.close();
        }
        Files.move(tmpFile.toPath(), outFile.toPath(), StandardCopyOption.REPLACE_EXISTING);
    } finally {
        if (tmpFile.exists()) {
            tmpFile["delete"]();
        }
    }
}

if (arguments.length < 2 || arguments.length % 2 != 0) {
    print("Kullanım: jjs -cp <UYAP jar'ları> uyap_native_converter.js -- <girdi1.udf> <çıktı1.pdf> [<girdi2.udf> <çıktı2.pdf> ...]");
    exit(2);
}

// Motorun DEBUG günlüğü her belgede binlerce satır basıyor; yalnızca uyarı ve hatalar kalsın.
try {
    var LoggerFactory = Java.type("org.slf4j.LoggerFactory");
    var Level = Java.type("ch.qos.logback.classic.Level");
    LoggerFactory.getLogger("ROOT").setLevel(Level.WARN);
} catch (e) {
    // günlük ayarlanamazsa dönüştürme yine çalışır
}

var exporter = findExportMethod();
var failures = 0;
for (var i = 0; i < arguments.length; i += 2) {
    var index = i / 2;
    if (exporter.error) {
        emit("UYAPCONV-ERR", index, exporter.error);
        failures++;
        continue;
    }
    try {
        convertOne(exporter, arguments[i], arguments[i + 1]);
        emit("UYAPCONV-OK", index);
    } catch (e) {
        emit("UYAPCONV-ERR", index, typeof e === "string" ? e : rootCauseMessage(e));
        failures++;
    }
}
exit(failures > 0 ? 1 : 0);
