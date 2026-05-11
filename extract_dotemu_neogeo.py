from pathlib import Path
import zipfile
import shutil
import zlib
import hashlib

ROOT = Path(__file__).resolve().parent

def crc32_hex(data):
    return f"{zlib.crc32(data) & 0xffffffff:08x}"

def sha1_hex(data):
    return hashlib.sha1(data).hexdigest()

def fail(msg):
    print()
    print("ERROR:", msg)
    print()
    raise SystemExit(1)

def require_file(name, size=None):
    path = ROOT / name

    if not path.is_file():
        fail(f"Missing required file: {name}")

    if size is not None and path.stat().st_size != size:
        fail(f"Wrong size for {name}: {path.stat().st_size} bytes, expected {size}")

    return path

def check_hash(label, data, expected_crc=None, expected_sha1=None):
    got_crc = crc32_hex(data)
    got_sha1 = sha1_hex(data)

    crc_ok = expected_crc is None or got_crc == expected_crc
    sha1_ok = expected_sha1 is None or got_sha1 == expected_sha1

    status = "OK" if crc_ok and sha1_ok else "BAD"

    print(f"{status:3} {label:14} size={len(data):8} crc={got_crc} sha1={got_sha1}")

    if expected_crc and got_crc != expected_crc:
        print(f"    expected crc : {expected_crc}")

    if expected_sha1 and got_sha1 != expected_sha1:
        print(f"    expected sha1: {expected_sha1}")

    return crc_ok and sha1_ok

def sfix_reencode_source_bytes(data):
    output = bytearray()
    buffer = bytearray(32)

    for i in range(0, len(data), 32):
        for j in range(0, 8):
            buffer[0 + j]  = data[i + j * 4 + 2]
            buffer[8 + j]  = data[i + j * 4 + 3]
            buffer[16 + j] = data[i + j * 4]
            buffer[24 + j] = data[i + j * 4 + 1]
        output.extend(buffer)

    return bytes(output)

def tiles_reencode_pairs(tile_data, pairs, write_func):
    print()
    print("Starting tile re-encoding. This can take a while.")

    pos = 0

    for c_odd, c_even, crom_size in pairs:
        pair_data = tile_data[pos:pos + crom_size * 2]
        pos += crom_size * 2

        if len(pair_data) != crom_size * 2:
            fail(f"Not enough tile data for {c_odd}/{c_even}")

        outa = bytearray()
        outb = bytearray()

        def coltoneogeo(col):
            for row in col:
                bp0, bp1, bp2, bp3 = 0, 0, 0, 0
                px = bytearray()

                for b in row:
                    px.append(b & 0x0F)
                    px.append(b >> 4)

                for p in range(0, 8):
                    bp0 |= (px[p] & 1) << (7 - p)
                    bp1 |= ((px[p] >> 1) & 1) << (7 - p)
                    bp2 |= ((px[p] >> 2) & 1) << (7 - p)
                    bp3 |= ((px[p] >> 3) & 1) << (7 - p)

                outa.append(bp0)
                outa.append(bp1)
                outb.append(bp2)
                outb.append(bp3)

        total_tiles = len(pair_data) // 128

        for tile in range(0, len(pair_data), 128):
            lcol = []
            rcol = []
            brow = []

            for byte in range(0, 128):
                if ((byte // 4) % 2 == 0):
                    brow.append(pair_data[tile + byte])
                    if len(brow) == 4:
                        lcol.append(brow[:])
                        brow.clear()
                else:
                    brow.append(pair_data[tile + byte])
                    if len(brow) == 4:
                        rcol.append(brow[:])
                        brow.clear()

            coltoneogeo(rcol)
            coltoneogeo(lcol)

            tile_no = tile // 128
            if tile_no % 4096 == 0:
                print(f"{c_odd}/{c_even}: tile {tile_no} of {total_tiles}", end="\r", flush=True)

        print()
        write_func(c_odd, bytes(outa))
        write_func(c_even, bytes(outb))

def make_zip(zip_path, source_folder, file_list):
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name in file_list:
            path = source_folder / name
            if not path.is_file():
                fail(f"Cannot zip missing file: {name}")
            z.write(path, arcname=name)

    print(f"Created ZIP: {zip_path}")

def detect_game():
    if (ROOT / "lastblad_game_m68k").is_file():
        return "lastblad"

    if (ROOT / "twinspri_game_m68k").is_file():
        return "twinspri"

    fail("No supported Dotemu NeoGeo game detected. Expected lastblad_* or twinspri_* files.")

def run_lastblad():
    out = ROOT / "lastblad_extracted"
    tmp_game = out / "_tmp_game_files"
    tmp_bios = out / "_tmp_bios_files"
    game_zip = out / "lastblad.zip"
    bios_zip = out / "neogeo.zip"

    expected_game_crc32 = {
        "234-s1.s1":  "95561412",
        "234-c1.c1":  "9f7e2bd3",
        "234-c2.c2":  "80623d3c",
        "234-c3.c3":  "91ab1a30",
        "234-c4.c4":  "3d60b037",
        "234-c5.c5":  "1ba80cee",
        "234-c6.c6":  "beafd091",
    }

    expected_bios = {
        "000-lo.lo":   ("5a86cff2", "5992277debadeb64d1c1c64b0a92d9293eaf7e4a"),
        "sp-u2.sp1":  ("e72943de", "5c6bba07d2ec8ac95776aa3511109f5e1e2e92eb"),
        "vs-bios.rom": (None, None),
        "sfix.sfix":  ("c2ea0cfd", "fd4a618cdcdbf849374f0a50dd8efe9dbab706c3"),
    }

    def write_game_file(name, data):
        path = tmp_game / name
        path.write_bytes(data)

        exp_crc = expected_game_crc32.get(name)
        if exp_crc:
            check_hash(name, data, expected_crc=exp_crc)
        else:
            check_hash(name, data)

    def write_bios_file(name, data):
        path = tmp_bios / name
        path.write_bytes(data)

        exp_crc, exp_sha1 = expected_bios.get(name, (None, None))
        check_hash(name, data, expected_crc=exp_crc, expected_sha1=exp_sha1)

    print("Detected: The Last Blade")
    print(f"Source folder: {ROOT}")
    print(f"Output folder: {out}")
    print()

    if out.exists():
        shutil.rmtree(out)

    out.mkdir(parents=True, exist_ok=True)
    tmp_game.mkdir(parents=True, exist_ok=True)
    tmp_bios.mkdir(parents=True, exist_ok=True)

    require_file("lastblad_game_m68k", 5_242_880)
    require_file("lastblad_game_z80", 131_072)
    require_file("lastblad_game_sfix", 131_072)
    require_file("lastblad_adpcma", 16_777_216)
    require_file("lastblad_tiles", 41_943_040)
    require_file("lastblad_zoom_table", 131_072)
    require_file("lastblad_bios_m68k", 131_072)
    require_file("lastblad_bios_m68k_jap", 131_072)
    require_file("lastblad_bios_sfix", 131_072)

    m68k = require_file("lastblad_game_m68k").read_bytes()
    write_game_file("234-p1.p1", m68k[:1_048_576])
    write_game_file("234-p2.sp2", m68k[1_048_576:])

    write_game_file("234-m1.m1", require_file("lastblad_game_z80").read_bytes())
    write_game_file("234-s1.s1", sfix_reencode_source_bytes(require_file("lastblad_game_sfix").read_bytes()))

    adpcm = require_file("lastblad_adpcma").read_bytes()
    write_game_file("234-v1.v1", adpcm[0:4_194_304])
    write_game_file("234-v2.v2", adpcm[4_194_304:8_388_608])
    write_game_file("234-v3.v3", adpcm[8_388_608:12_582_912])
    write_game_file("234-v4.v4", adpcm[12_582_912:16_777_216])

    tiles_reencode_pairs(
        require_file("lastblad_tiles").read_bytes(),
        [
            ("234-c1.c1", "234-c2.c2", 8 * 1024 * 1024),
            ("234-c3.c3", "234-c4.c4", 8 * 1024 * 1024),
            ("234-c5.c5", "234-c6.c6", 4 * 1024 * 1024),
        ],
        write_game_file
    )

    game_files = [
        "234-p1.p1", "234-p2.sp2", "234-m1.m1", "234-s1.s1",
        "234-v1.v1", "234-v2.v2", "234-v3.v3", "234-v4.v4",
        "234-c1.c1", "234-c2.c2", "234-c3.c3", "234-c4.c4", "234-c5.c5", "234-c6.c6",
    ]

    make_zip(game_zip, tmp_game, game_files)

    write_bios_file("000-lo.lo", require_file("lastblad_zoom_table").read_bytes())
    write_bios_file("sp-u2.sp1", require_file("lastblad_bios_m68k").read_bytes())
    write_bios_file("vs-bios.rom", require_file("lastblad_bios_m68k_jap").read_bytes())
    write_bios_file("sfix.sfix", sfix_reencode_source_bytes(require_file("lastblad_bios_sfix").read_bytes()))

    make_zip(
        bios_zip,
        tmp_bios,
        ["000-lo.lo", "sp-u2.sp1", "vs-bios.rom", "sfix.sfix"]
    )

    shutil.rmtree(tmp_game)
    shutil.rmtree(tmp_bios)

    print()
    print("Done.")
    print(f"Final output: {game_zip}")
    print(f"Final output: {bios_zip}")
    print()
    print("Note: neogeo.zip contains only BIOS files included with this Dotemu release. It may be incomplete for a full MAME NeoGeo BIOS set.")

def run_twinspri():
    out = ROOT / "twinspri_extracted"
    tmp_game = out / "_tmp_game_files"
    tmp_bios = out / "_tmp_bios_files"
    game_zip = out / "twinspri.zip"
    bios_zip = out / "neogeo.zip"

    expected_game_crc32 = {
        "224-p1.p1": "7697e445",
        "224-s1.s1": "eeed5758",
        "224-m1.m1": "364d6f96",
        "224-v1.v1": "ff57f088",
        "224-v2.v2": "7ad26599",
        "224-c1.c1": "f7da64ab",
        "224-c2.c2": "4c09bbfb",
        "224-c3.c3": "c59e4129",
        "224-c4.c4": "b5532e53",
    }

    expected_bios = {
        "000-lo.lo":  ("5a86cff2", "5992277debadeb64d1c1c64b0a92d9293eaf7e4a"),
        "sp-u2.sp1": ("e72943de", "5c6bba07d2ec8ac95776aa3511109f5e1e2e92eb"),
        "sfix.sfix": ("c2ea0cfd", "fd4a618cdcdbf849374f0a50dd8efe9dbab706c3"),
    }

    def write_game_file(name, data):
        path = tmp_game / name
        path.write_bytes(data)

        exp_crc = expected_game_crc32.get(name)
        if exp_crc:
            check_hash(name, data, expected_crc=exp_crc)
        else:
            check_hash(name, data)

    def write_bios_file(name, data):
        path = tmp_bios / name
        path.write_bytes(data)

        exp_crc, exp_sha1 = expected_bios.get(name, (None, None))
        check_hash(name, data, expected_crc=exp_crc, expected_sha1=exp_sha1)

    print("Detected: Twinkle Star Sprites")
    print(f"Source folder: {ROOT}")
    print(f"Output folder: {out}")
    print()

    if out.exists():
        shutil.rmtree(out)

    out.mkdir(parents=True, exist_ok=True)
    tmp_game.mkdir(parents=True, exist_ok=True)
    tmp_bios.mkdir(parents=True, exist_ok=True)

    require_file("twinspri_game_m68k", 4_194_304)
    require_file("twinspri_game_z80", 131_072)
    require_file("twinspri_game_sfix", 131_072)
    require_file("twinspri_adpcm", 6_291_456)
    require_file("twinspri_tiles", 10_485_760)
    require_file("twinspri_zoom_table", 131_072)
    require_file("twinspri_bios_m68k", 131_072)
    require_file("twinspri_bios_sfix", 131_072)

    m68k = require_file("twinspri_game_m68k").read_bytes()

    # Twinkle Star Sprites Dotemu layout:
    # first 2MB are used, split into two 1MB halves, then reversed.
    bottom = m68k[0:1_048_576]
    top = m68k[1_048_576:2_097_152]
    write_game_file("224-p1.p1", top + bottom)

    write_game_file("224-m1.m1", require_file("twinspri_game_z80").read_bytes())
    write_game_file("224-s1.s1", sfix_reencode_source_bytes(require_file("twinspri_game_sfix").read_bytes()))

    adpcm = require_file("twinspri_adpcm").read_bytes()
    write_game_file("224-v1.v1", adpcm[0:4_194_304])
    write_game_file("224-v2.v2", adpcm[4_194_304:6_291_456])

    tiles_reencode_pairs(
        require_file("twinspri_tiles").read_bytes(),
        [
            ("224-c1.c1", "224-c2.c2", 4 * 1024 * 1024),
            ("224-c3.c3", "224-c4.c4", 1 * 1024 * 1024),
        ],
        write_game_file
    )

    game_files = [
        "224-p1.p1", "224-s1.s1", "224-m1.m1",
        "224-v1.v1", "224-v2.v2",
        "224-c1.c1", "224-c2.c2", "224-c3.c3", "224-c4.c4",
    ]

    make_zip(game_zip, tmp_game, game_files)

    write_bios_file("000-lo.lo", require_file("twinspri_zoom_table").read_bytes())
    write_bios_file("sp-u2.sp1", require_file("twinspri_bios_m68k").read_bytes())
    write_bios_file("sfix.sfix", sfix_reencode_source_bytes(require_file("twinspri_bios_sfix").read_bytes()))

    make_zip(
        bios_zip,
        tmp_bios,
        ["000-lo.lo", "sp-u2.sp1", "sfix.sfix"]
    )

    shutil.rmtree(tmp_game)
    shutil.rmtree(tmp_bios)

    print()
    print("Done.")
    print(f"Final output: {game_zip}")
    print(f"Final output: {bios_zip}")
    print()
    print("Note: neogeo.zip contains only BIOS files included with this Dotemu release. It may be incomplete for a full MAME NeoGeo BIOS set.")

def main():
    game = detect_game()

    if game == "lastblad":
        run_lastblad()
    elif game == "twinspri":
        run_twinspri()
    else:
        fail(f"Unsupported game: {game}")

if __name__ == "__main__":
    main()
