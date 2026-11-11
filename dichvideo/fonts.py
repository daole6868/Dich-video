"""Danh mục phông chữ phụ đề: đọc tên họ phông và thông số trực tiếp từ tệp TTF/OTF.

libass tìm phông theo *tên họ kiểu cũ* (name ID 1) cộng cờ đậm/nghiêng, nên danh mục
dùng đúng tên đó làm khoá. Hệ số ``em_ratio`` cho giao diện biết cỡ chữ CSS tương ứng
với cỡ chữ ASS (libass tính cỡ theo usWinAscent + usWinDescent chứ không theo em).
"""

from __future__ import annotations

import logging
import shutil
import struct
import threading
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

EXTENSIONS = (".ttf", ".otf")
DEFAULT_FONT = "Be Vietnam Pro"
_VIETNAMESE_PROBE = "ạảãấầẩẫậắằẳẵặẹẻẽếềểễệịỉĩọỏõốồổỗộớờởỡợụủũứừửữựỳỵỷỹđƠƯ"

_cache: dict | None = None
_lock = threading.Lock()


def _tables(data: bytes) -> dict[str, tuple[int, int]]:
    if len(data) < 12 or data[:4] == b"ttcf":  # bộ sưu tập .ttc không hỗ trợ
        return {}
    num = struct.unpack(">H", data[4:6])[0]
    out = {}
    for i in range(num):
        rec = data[12 + i * 16:28 + i * 16]
        if len(rec) < 16:
            break
        tag, _chk, off, length = struct.unpack(">4sIII", rec)
        out[tag.decode("latin-1")] = (off, length)
    return out


def _names(data: bytes, table: tuple[int, int]) -> dict[int, str]:
    off, length = table
    blob = data[off:off + length]
    if len(blob) < 6:
        return {}
    _fmt, count, string_off = struct.unpack(">HHH", blob[:6])
    best: dict[int, tuple[int, str]] = {}
    for i in range(count):
        rec = blob[6 + i * 12:18 + i * 12]
        if len(rec) < 12:
            break
        platform, _enc, lang, name_id, n, o = struct.unpack(">HHHHHH", rec)
        raw = blob[string_off + o:string_off + o + n]
        try:
            if platform in (0, 3):
                text, rank = raw.decode("utf-16-be"), (3 if lang == 0x409 else 2)
            elif platform == 1:
                text, rank = raw.decode("mac_roman"), 1
            else:
                continue
        except UnicodeDecodeError:
            continue
        text = text.strip("\x00 ")
        if text and (name_id not in best or rank > best[name_id][0]):
            best[name_id] = (rank, text)
    return {k: v[1] for k, v in best.items()}


def _cmap_has(data: bytes, table: tuple[int, int], chars: str) -> bool:
    """Kiểm tra nhanh bảng cmap định dạng 4 (BMP) có đủ các ký tự không."""
    off, length = table
    blob = data[off:off + length]
    if len(blob) < 4:
        return True
    num = struct.unpack(">H", blob[2:4])[0]
    sub = None
    for i in range(num):
        rec = blob[4 + i * 8:12 + i * 8]
        if len(rec) < 8:
            break
        platform, enc, o = struct.unpack(">HHI", rec)
        if (platform, enc) in ((3, 1), (0, 3), (0, 4), (3, 10)) and blob[o:o + 2] == b"\x00\x04":
            sub = blob[o:]
            break
    if sub is None or len(sub) < 16:
        return True  # không đọc được thì không kết luận là thiếu
    seg_count = struct.unpack(">H", sub[6:8])[0] // 2
    ends = struct.unpack(f">{seg_count}H", sub[14:14 + 2 * seg_count])
    starts = struct.unpack(f">{seg_count}H", sub[16 + 2 * seg_count:16 + 4 * seg_count])
    for ch in chars:
        cp = ord(ch)
        if not any(s <= cp <= e for s, e in zip(starts, ends)):
            return False
    return True


def read_font(path: Path) -> dict | None:
    """Thông tin một tệp phông, hoặc ``None`` nếu không đọc được."""
    try:
        data = path.read_bytes()
        tables = _tables(data)
        if "name" not in tables or "head" not in tables:
            return None
        names = _names(data, tables["name"])
        family = names.get(1) or names.get(16)
        if not family:
            return None
        upm = struct.unpack(">H", data[tables["head"][0] + 18:tables["head"][0] + 20])[0] or 1000
        bold = italic = False
        asc = desc = 0
        if "OS/2" in tables and tables["OS/2"][1] >= 78:
            o = tables["OS/2"][0]
            weight = struct.unpack(">H", data[o + 4:o + 6])[0]
            fs = struct.unpack(">H", data[o + 62:o + 64])[0]
            asc, desc = struct.unpack(">HH", data[o + 74:o + 78])
            italic = bool(fs & 0x01)
            bold = bool(fs & 0x20) or weight >= 700
        if asc + desc == 0 and "hhea" in tables:
            h = tables["hhea"][0]
            a, d = struct.unpack(">hh", data[h + 4:h + 8])
            asc, desc = a, -d
        ratio = upm / (asc + desc) if asc + desc > 0 else 0.8
        return {
            "family": family,
            "display": names.get(16) or family,
            "style": names.get(17) or names.get(2) or "Regular",
            "bold": bold,
            "italic": italic,
            "em_ratio": round(ratio, 4),
            "vietnamese": _cmap_has(data, tables["cmap"], _VIETNAMESE_PROBE) if "cmap" in tables else True,
            "file": path.name,
        }
    except (OSError, struct.error, IndexError, ValueError) as e:
        log.warning("Không đọc được phông %s: %s", path.name, e)
        return None


def _scan() -> dict:
    faces = []
    for folder, origin in ((config.FONTS_DIR, "kem-theo"), (config.USER_FONTS_DIR, "nguoi-dung")):
        if not folder.is_dir():
            continue
        for p in sorted(folder.iterdir()):
            if p.suffix.lower() in EXTENSIONS and p.is_file():
                info = read_font(p)
                if info:
                    info.update(origin=origin, path=str(p),
                                url=f"/fonts/{'user/' if origin == 'nguoi-dung' else ''}{p.name}")
                    faces.append(info)
    families: dict[str, dict] = {}
    for f in faces:
        fam = families.setdefault(f["family"], {
            "family": f["family"], "em_ratio": f["em_ratio"], "vietnamese": True,
            "has_bold": False, "has_italic": False, "origin": f["origin"], "faces": []})
        fam["faces"].append({k: f[k] for k in ("file", "url", "bold", "italic", "style")})
        fam["has_bold"] |= f["bold"]
        fam["has_italic"] |= f["italic"]
        fam["vietnamese"] &= f["vietnamese"]
        if not f["bold"] and not f["italic"]:
            fam["em_ratio"] = f["em_ratio"]
    ordered = sorted(families.values(),
                     key=lambda x: (x["family"] != DEFAULT_FONT, x["origin"] != "kem-theo", x["family"].lower()))
    return {"faces": faces, "families": ordered}


def catalog(refresh: bool = False) -> dict:
    global _cache
    with _lock:
        if _cache is None or refresh:
            _cache = _scan()
        return _cache


def families() -> list[dict]:
    return catalog()["families"]


def resolve_family(name: str) -> str:
    """Tên họ phông hợp lệ: trả về mặc định nếu phông đã chọn không còn trong danh mục."""
    known = {f["family"] for f in families()}
    if name in known:
        return name
    return DEFAULT_FONT if DEFAULT_FONT in known else (next(iter(known), "Arial"))


def em_ratio(name: str) -> float:
    """Tỉ lệ em / chiều cao dòng của một họ phông (dùng để quy đổi cỡ chữ sang ASS)."""
    for fam in families():
        if fam["family"] == name:
            return float(fam["em_ratio"])
    return 0.7


def copy_fonts_to(dest: Path, family: str | None = None) -> None:
    """Chép phông vào thư mục làm việc của lần xuất video.

    ffmpeg được chạy ngay trong thư mục đó và trỏ ``fontsdir`` bằng đường dẫn tương đối, nên
    không vướng chuyện ký tự ổ đĩa ``C:`` hay dấu cách trong bộ lọc trên Windows.
    """
    dest.mkdir(parents=True, exist_ok=True)
    for face in catalog()["faces"]:
        if family is None or face["family"] == family:
            target = dest / face["file"]
            if not target.exists():
                shutil.copy2(face["path"], target)
