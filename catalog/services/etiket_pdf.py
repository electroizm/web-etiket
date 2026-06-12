"""
PDF etiket üretimi.

Eski projedeki (etiket-web) ReportLab tasarımı birebir korunarak yeni model
yapısına uyarlandı. A4 landscape, 4 köşe kesim çizgisi, header görseli (varsa),
QR kod (sağ üst), eğik indirim etiketi, tablo (başlık + ürünler + kombinasyonlar),
yerli üretim logosu (sağ alt), dipnot.

Veri haritası (kullanıcının belirttiği gibi):
- Başlık (BEND Koltuk Takımı)        → koleksiyon.takim_adi
- Ürün satırları (sadece secili)      → urun_koleksiyon.etiket_secili = TRUE
- İNDİRİMLİ FİYAT                      → urun.son_perakende_fiyat
- LİSTE FİYATI                         → urun.son_liste_fiyat
- Kombinasyon adı                      → kombinasyon.ad
- Kombinasyon toplam indirimli/liste   → hesapla_kombinasyon_toplam(...)
- Eğik etiketin %X'i                   → ilk kombinasyonun indirim_yuzde'si (5'in katına yuvarlı)
- QR URL                               → koleksiyon.takim_urun.url
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from io import BytesIO
from pathlib import Path

import qrcode
import requests
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from catalog.sa_models import Kombinasyon, KombinasyonUrun, Koleksiyon, Urun, urun_koleksiyon
from catalog.services.ayarlar import slogan_url_aktif, yerli_uretim_url_aktif
from catalog.services.kombinasyon import hesapla_kombinasyon_toplam

log = logging.getLogger(__name__)


# Etikette gösterilebilecek maksimum satır sayısı (sütun başlıkları hariç).
# Aşılırsa PDF üretimi durdurulur (EtiketSatirAsim hatası).
ETIKET_MAX_SATIR = 15


class EtiketSatirAsim(Exception):
    """15 satır limiti aşıldığında fırlatılır. Mesajı kullanıcıya gösterilir."""

    def __init__(self, toplam: int, urun_sayisi: int, kombi_sayisi: int):
        self.toplam = toplam
        self.urun_sayisi = urun_sayisi
        self.kombi_sayisi = kombi_sayisi
        super().__init__(
            f"Etikette en fazla {ETIKET_MAX_SATIR} satır olabilir. "
            f"Şu an {toplam} satır var ({urun_sayisi} ürün + {kombi_sayisi} kombinasyon). "
            f"İşaretli kombinasyon veya ürün sayısını azalt."
        )


class EtiketBosSecim(Exception):
    """Hiç ürün veya kombinasyon işaretli değilse fırlatılır."""

    def __init__(self):
        super().__init__(
            "Etikete eklenecek hiçbir ürün veya kombinasyon işaretlenmemiş. "
            "Ürün kartlarındaki ve kombinasyon listesindeki kutucuklardan en az birini işaretle."
        )


# ─── Yardımcılar ─────────────────────────────────────────────────────────────


def _format_price(price: int | float | None) -> str:
    """12500 → '12.500 TL' (Türkçe binlik nokta)."""
    if price is None or price == 0:
        return "0 TL"
    return f"{float(price):,.0f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _qr_image(url: str) -> ImageReader:
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def _yukari_5e_yuvarla(yuzde: int) -> int:
    """19 → 20, 13 → 15, 25 → 25 (zaten 5'in katı)."""
    if yuzde <= 0:
        return 0
    return -(-yuzde // 5) * 5


# ─── Font yönetimi ───────────────────────────────────────────────────────────

_FONT_CANDIDATES: list[tuple[str, str]] = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSans.ttf",
     "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
]


def _safe_setup_fonts() -> tuple[str, str]:
    """İlk bulunan font'u 'Arial'/'Arial-Bold' adıyla kaydet. Bulunamazsa Helvetica fallback."""
    for regular, bold in _FONT_CANDIDATES:
        if os.path.exists(regular) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont("Arial", regular))
                pdfmetrics.registerFont(TTFont("Arial-Bold", bold))
                return "Arial", "Arial-Bold"
            except Exception:
                continue
    # Helvetica TR karakter destekleme — son çare
    return "Helvetica", "Helvetica-Bold"


# ─── Görsel yolları (geçici: lokal dosya, yoksa placeholder) ─────────────────

def _try_load_local_image(filename: str) -> ImageReader | None:
    """static/img/ altında dosya varsa yükle, yoksa None."""
    from django.conf import settings as dj_settings
    base_dir = Path(dj_settings.BASE_DIR) if hasattr(dj_settings, "BASE_DIR") else Path.cwd()
    path = base_dir / "static" / "img" / filename
    if path.exists():
        try:
            return ImageReader(str(path))
        except Exception:
            return None
    return None


def _try_load_remote_image(url: str | None) -> ImageReader | None:
    """Public URL'den indir, ImageReader olarak döner. Hatada None."""
    if not url:
        return None
    try:
        r = requests.get(url, timeout=8)
        if r.status_code == 200 and r.content:
            return ImageReader(BytesIO(r.content))
    except Exception as e:
        log.warning("Slogan görseli indirilemedi: %s — %s", url, e)
    return None


def _load_etiket_gorselleri(
    session: Session,
) -> tuple[ImageReader | None, ImageReader | None]:
    """(header_img, yerli_img) — slogan ve yerli üretim görsellerini yükler.

    Remote URL → lokal dosya fallback. Çoklu yazdırmada her sayfa için
    yeniden indirilmemesi için çağıran TEK SEFER yükleyip _draw_etiket_page'e
    geçirir (63 sayfa × 2 görsel = 126 HTTP isteği yerine 2 istek).
    """
    header_img = (
        _try_load_remote_image(slogan_url_aktif(session))
        or _try_load_local_image("etiket_baslik.png")
    )
    yerli_img = (
        _try_load_remote_image(yerli_uretim_url_aktif(session))
        or _try_load_local_image("yerli_uretim.jpg")
        or _try_load_local_image("yerli_uretim.png")
    )
    return header_img, yerli_img


# ─── Çizim fonksiyonları ─────────────────────────────────────────────────────


def _draw_cutting_lines(c: canvas.Canvas) -> None:
    """4 köşeye kesim çizgisi."""
    page_width, page_height = landscape(A4)
    cizgi = 60
    c.setLineWidth(2)
    c.line(10, page_height - 10, 10 + cizgi, page_height - 10)
    c.line(10, page_height - 10, 10, page_height - 10 - cizgi)
    c.line(page_width - 10, page_height - 10, page_width - 10 - cizgi, page_height - 10)
    c.line(page_width - 10, page_height - 10, page_width - 10, page_height - 10 - cizgi)
    c.line(10, 10, 10 + cizgi, 10)
    c.line(10, 10, 10, 10 + cizgi)
    c.line(page_width - 10, 10, page_width - 10 - cizgi, 10)
    c.line(page_width - 10, 10, page_width - 10, 10 + cizgi)


def _draw_indirim_etiketi(
    c: canvas.Canvas, x: float, y: float, indirim_yuzde: int, font_bold: str
) -> None:
    """Eğik siyah indirim etiketi (header sağında, QR solunda)."""
    if not indirim_yuzde or indirim_yuzde <= 0:
        return
    w, h = 110, 45
    c.saveState()
    c.translate(x, y)
    c.rotate(-17)
    c.setFillColorRGB(0.07, 0.07, 0.07)
    c.roundRect(0, 0, w, h, 8, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont(font_bold, 36)
    text = f"-{indirim_yuzde}%"
    text_w = c.stringWidth(text, font_bold, 36)
    c.drawString((w - text_w) / 2, h / 2 - 13, text)
    c.restoreState()


def _draw_header_placeholder(c: canvas.Canvas, font_bold: str) -> None:
    """Banner görseli yoksa basit metin başlığı."""
    page_width, page_height = landscape(A4)
    c.saveState()
    c.setFillColorRGB(0.96, 0.94, 0.88)
    c.roundRect(80, page_height - 165, 480, 80, 10, fill=1, stroke=0)
    c.setFillColorRGB(0.07, 0.07, 0.07)
    c.setFont(font_bold, 22)
    c.drawString(100, page_height - 120, "Doğtaş'ta")
    c.drawString(100, page_height - 145, "Bahar Fırsatları")
    c.restoreState()


def _draw_yerli_uretim_placeholder(c: canvas.Canvas, font_bold: str) -> None:
    """Yerli üretim görseli yoksa basit metin etiketi."""
    page_width, _ = landscape(A4)
    c.saveState()
    c.setFillColorRGB(0.07, 0.07, 0.07)
    c.roundRect(page_width - 180, 80, 100, 30, 6, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont(font_bold, 9)
    c.drawCentredString(page_width - 130, 92, "YERLİ ÜRETİM")
    c.restoreState()


# ─── Tablo çizimi ────────────────────────────────────────────────────────────


def _draw_table(
    c: canvas.Canvas,
    *,
    baslik: str,
    urunler: list[Urun],
    kombinasyonlar: list[tuple[Kombinasyon, dict]],
    page_height: float,
    font: str,
    font_bold: str,
) -> None:
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleStyle", parent=styles["Normal"],
        fontName=font_bold, fontSize=16, leading=18,
        textColor=colors.HexColor("#000000"), alignment=0,
    )
    product_style = ParagraphStyle(
        "ProductStyle", parent=styles["Normal"],
        fontName=font, fontSize=10, leading=12, textColor=colors.black,
    )
    aciklama_style = ParagraphStyle(
        "AciklamaStyle", parent=styles["Normal"],
        fontName=font_bold, fontSize=14, leading=16,
        textColor=colors.HexColor("#000000"),
        spaceBefore=10, spaceAfter=10,
    )

    data: list[list] = []
    data.append([Paragraph(baslik, title_style), "İNDİRİMLİ FİYAT", "LİSTE FİYATI"])

    for u in urunler:
        data.append([
            Paragraph(u.urun_adi_tam, product_style),
            _format_price(u.son_perakende_fiyat),
            _format_price(u.son_liste_fiyat),
        ])

    product_count = len(urunler)

    for kombi, toplam in kombinasyonlar:
        data.append([
            Paragraph(kombi.ad.title(), aciklama_style),
            _format_price(toplam.get("toplam_perakende")),
            _format_price(toplam.get("toplam_liste")),
        ])

    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D3D3D3")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.black),
        ("ALIGN",      (0, 0), (-1, -1), "LEFT"),
        ("ALIGN",      (1, 0), (-1, -1), "RIGHT"),
        ("FONTNAME",   (0, 0), (-1, 0), font_bold),
        ("FONTSIZE",   (0, 0), (-1, 0), 13),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("GRID",       (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
            [colors.HexColor("#F5F5F5"), colors.white]),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME",   (0, product_count + 1), (-1, -1), font_bold),
        ("FONTSIZE",   (0, product_count + 1), (-1, -1), 14),
    ])

    col_widths = [landscape(A4)[0] - 425, 135, 125]
    row_heights = [30] + [17] * product_count
    if kombinasyonlar:
        row_heights += [20] * len(kombinasyonlar)

    table = Table(data, colWidths=col_widths, rowHeights=row_heights)
    table.setStyle(style)
    table.wrapOn(c, landscape(A4)[0], landscape(A4)[1])
    table.drawOn(c, 80, page_height - 180 - table._height)


# ─── Per-page çizim ───────────────────────────────────────────────────────────


def _load_kol_sayfa_verisi(session: Session, koleksiyon_id: int):
    """(kol, urunler, kombi_data) döner. Yoksa (None, [], []) döner.

    Validasyon:
      - kol bulunamadı → (None, ...) → çağıran "atla" der
      - takim_adi boş → (None, ...) → çağıran "atla" der

    EtiketBosSecim/EtiketSatirAsim BURADA fırlatılır (single-mode için);
    multi-mode bunları yakalayıp atlar.
    """
    kol = session.scalar(
        select(Koleksiyon)
        .where(Koleksiyon.id == koleksiyon_id)
        .options(selectinload(Koleksiyon.takim_urun))
    )
    if kol is None:
        return None, [], []
    if not (kol.takim_adi or "").strip():
        return None, [], []

    # Etikette gösterilecek ürünler — drag-and-drop sırasında (siralama).
    urunler_stmt = (
        select(Urun)
        .join(urun_koleksiyon, urun_koleksiyon.c.urun_id == Urun.id)
        .where(
            urun_koleksiyon.c.koleksiyon_id == kol.id,
            urun_koleksiyon.c.etiket_secili.is_(True),
        )
        .order_by(urun_koleksiyon.c.siralama.asc(), Urun.id.asc())
    )
    urunler = list(session.scalars(urunler_stmt).all())

    kombi_stmt = (
        select(Kombinasyon)
        .where(
            Kombinasyon.koleksiyon_id == kol.id,
            Kombinasyon.etiket_secili.is_(True),
        )
        .order_by(Kombinasyon.sira, Kombinasyon.id)
        .options(selectinload(Kombinasyon.urunler).selectinload(KombinasyonUrun.urun))
    )
    kombiler = list(session.scalars(kombi_stmt).all())
    kombi_data = [(k, hesapla_kombinasyon_toplam(k)) for k in kombiler]

    toplam_satir = len(urunler) + len(kombi_data)
    if toplam_satir == 0:
        raise EtiketBosSecim()
    if toplam_satir > ETIKET_MAX_SATIR:
        raise EtiketSatirAsim(toplam_satir, len(urunler), len(kombi_data))

    return kol, urunler, kombi_data


def _load_coklu_kol_verisi(
    session: Session, koleksiyon_ids: list[int]
) -> list[tuple[Koleksiyon, list[Urun], list[tuple[Kombinasyon, dict]]]]:
    """Çoklu yazdırma için tüm koleksiyonların verisini TOPLU sorgularla yükler
    (koleksiyon başına 3-4 sorgu yerine toplam ~6 sorgu — 60+ koleksiyonda
    Render↔Supabase gecikmesi belirleyici olduğu için kritik).

    Geçersiz koleksiyonlar (bulunamadı, takım atanmamış, işaretli satır yok,
    satır limiti aşımı) log'lanıp atlanır. Girişteki id sırası korunur.
    """
    ids = list(dict.fromkeys(koleksiyon_ids))  # dedupe, sıra koru
    if not ids:
        return []

    kollar = {
        kol.id: kol
        for kol in session.scalars(
            select(Koleksiyon)
            .where(Koleksiyon.id.in_(ids))
            .options(selectinload(Koleksiyon.takim_urun))
        )
    }

    urun_rows = session.execute(
        select(urun_koleksiyon.c.koleksiyon_id, Urun)
        .join(Urun, Urun.id == urun_koleksiyon.c.urun_id)
        .where(
            urun_koleksiyon.c.koleksiyon_id.in_(ids),
            urun_koleksiyon.c.etiket_secili.is_(True),
        )
        .order_by(urun_koleksiyon.c.siralama.asc(), Urun.id.asc())
    ).all()
    urunler_map: dict[int, list[Urun]] = {}
    for kol_id, urun in urun_rows:
        urunler_map.setdefault(kol_id, []).append(urun)

    kombiler = session.scalars(
        select(Kombinasyon)
        .where(
            Kombinasyon.koleksiyon_id.in_(ids),
            Kombinasyon.etiket_secili.is_(True),
        )
        .order_by(Kombinasyon.sira, Kombinasyon.id)
        .options(selectinload(Kombinasyon.urunler).selectinload(KombinasyonUrun.urun))
    ).all()
    kombi_map: dict[int, list[tuple[Kombinasyon, dict]]] = {}
    for k in kombiler:
        kombi_map.setdefault(k.koleksiyon_id, []).append(
            (k, hesapla_kombinasyon_toplam(k))
        )

    sayfalar = []
    for kid in ids:
        kol = kollar.get(kid)
        if kol is None or not (kol.takim_adi or "").strip():
            log.warning(
                "Çoklu PDF · koleksiyon %s atlandı: bulunamadı veya takım atanmamış",
                kid,
            )
            continue
        urunler = urunler_map.get(kid, [])
        kombi_data = kombi_map.get(kid, [])
        toplam = len(urunler) + len(kombi_data)
        if toplam == 0:
            log.warning(
                "Çoklu PDF · koleksiyon %s atlandı: işaretli ürün/kombinasyon yok", kid
            )
            continue
        if toplam > ETIKET_MAX_SATIR:
            log.warning(
                "Çoklu PDF · koleksiyon %s atlandı: %s satır (limit %s)",
                kid, toplam, ETIKET_MAX_SATIR,
            )
            continue
        sayfalar.append((kol, urunler, kombi_data))
    return sayfalar


def _draw_etiket_page(
    c: canvas.Canvas,
    kol: Koleksiyon,
    urunler: list[Urun],
    kombi_data: list[tuple[Kombinasyon, dict]],
    font: str,
    font_bold: str,
    *,
    header_img: ImageReader | None,
    yerli_img: ImageReader | None,
) -> None:
    """Verilen kanvasın o anki sayfasına bir koleksiyonun etiket içeriğini çizer.
    Verinin önceden validate edilmiş, görsellerin _load_etiket_gorselleri ile
    yüklenmiş olması beklenir (multi-page'de sayfa başına indirme olmasın diye).
    """
    page_width, page_height = landscape(A4)

    # Header (slogan banner)
    if header_img is not None:
        c.drawImage(header_img, -10, page_height - 175, width=590, height=90,
                    preserveAspectRatio=True, mask='auto')
    else:
        _draw_header_placeholder(c, font_bold)

    _draw_cutting_lines(c)

    # QR — takim ürününün url'i
    qr_url = (kol.takim_urun.url if kol.takim_urun else None) or ""
    if qr_url:
        qr = _qr_image(qr_url)
        c.drawImage(qr, page_width - 185, page_height - 175, width=100, height=100)

    # İndirim etiketi: ilk kombinasyonun indirim_yuzde'sini 5'in katına yuvarla
    indirim_yuzde = 0
    if kombi_data:
        ilk_iy = kombi_data[0][1].get("indirim_yuzde") or 0
        indirim_yuzde = _yukari_5e_yuvarla(ilk_iy)
    _draw_indirim_etiketi(c, x=510, y=page_height - 140,
                          indirim_yuzde=indirim_yuzde, font_bold=font_bold)

    # Yerli üretim logosu
    if yerli_img is not None:
        c.drawImage(yerli_img, page_width - 180, 80, width=100, height=30,
                    preserveAspectRatio=True, mask='auto')
    else:
        _draw_yerli_uretim_placeholder(c, font_bold)

    _draw_table(
        c,
        baslik=kol.takim_adi,
        urunler=urunler,
        kombinasyonlar=kombi_data,
        page_height=page_height,
        font=font,
        font_bold=font_bold,
    )

    c.setFont(font, 9)
    dipnot = (
        f"Fiyat Değişiklik Tarihi: {datetime.now().strftime('%d.%m.%Y')} / "
        f"Fiyatlara KDV dahildir / Üretim Yeri: TÜRKİYE"
    )
    c.drawString(100, 80, dipnot)


# ─── Public API ──────────────────────────────────────────────────────────────


def pdf_koleksiyon_etiketi(session: Session, koleksiyon_id: int) -> bytes:
    """Bir koleksiyonun fiyat etiket PDF'ini üret (A4 landscape, tek sayfa).

    Yalnızca etiket_secili=True olan ürünler ve tüm kombinasyonlar PDF'e gider.
    Koleksiyona takım atanmamışsa veya etiket_secili ürün yoksa boş PDF döner.
    """
    font, font_bold = _safe_setup_fonts()

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    c.setTitle("Etiket")

    kol, urunler, kombi_data = _load_kol_sayfa_verisi(session, koleksiyon_id)
    if kol is None:
        # Kol bulunamadı veya takım yok — bilgilendirme sayfası
        # (görüntüleme hatasını UI tarafında daha güzel ele alıyoruz, ama
        # PDF de minimum mesaj göstersin)
        c.setFont(font, 14)
        c.drawString(100, 400, "Koleksiyon bulunamadı veya takım atanmamış.")
        c.save()
        return buf.getvalue()

    header_img, yerli_img = _load_etiket_gorselleri(session)
    _draw_etiket_page(c, kol, urunler, kombi_data, font, font_bold,
                      header_img=header_img, yerli_img=yerli_img)
    c.save()
    return buf.getvalue()


def pdf_coklu_koleksiyon_etiketi(
    session: Session, koleksiyon_ids: list[int]
) -> tuple[bytes, list[int]]:
    """Birden fazla koleksiyonun etiket PDF'ini tek doküman olarak üret.

    Her koleksiyon ayrı sayfa (A4 landscape). Geçersiz koleksiyonlar
    (kol bulunamadı, takım atanmamış, ürün yok, satır limiti aşımı)
    sessizce atlanır — kalanlar yine üretilir.

    Returns:
        (pdf_bytes, basilan_ids) — basilan_ids: PDF'e gerçekten sayfa olarak
        giren koleksiyon id'leri (son_yazdirma damgası bunlara vurulur).
    """
    font, font_bold = _safe_setup_fonts()

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    c.setTitle("Etiket")

    # Tüm koleksiyon verisi toplu sorgularla, görseller tek indirme ile
    sayfalar = _load_coklu_kol_verisi(session, koleksiyon_ids)
    header_img, yerli_img = _load_etiket_gorselleri(session)

    pages_drawn = 0
    basilan_ids: list[int] = []
    for kol, urunler, kombi_data in sayfalar:
        if pages_drawn > 0:
            c.showPage()  # önceki sayfayı kapat, yeni sayfa aç
        try:
            _draw_etiket_page(
                c, kol, urunler, kombi_data, font, font_bold,
                header_img=header_img,
                yerli_img=yerli_img,
            )
            pages_drawn += 1
            basilan_ids.append(kol.id)
        except Exception:
            log.exception("Çoklu PDF · koleksiyon %s çizim hatası", kol.id)
            # showPage zaten yapıldı, boş sayfa kalmasın diye yine de
            # increment ediyoruz (boş sayfayla devam, kullanıcı görür).
            pages_drawn += 1

    if pages_drawn == 0:
        c.setFont(font, 14)
        c.drawString(100, 400, "Yazdırılacak geçerli koleksiyon bulunamadı.")

    c.save()
    return buf.getvalue(), basilan_ids
