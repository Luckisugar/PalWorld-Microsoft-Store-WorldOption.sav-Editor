"""CLI worker for PlM sav ops — run under Python 3.12 with palooz."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# vendor next to tool root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from palworld_ms import sav  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "action",
        choices=["probe", "read_ints", "set_coop", "dump_gvas", "pack_gvas"],
    )
    p.add_argument("--in", dest="inp", required=False)
    p.add_argument("--out", dest="out", required=False)
    p.add_argument("--coop", type=int, default=10)
    p.add_argument("--magic", default="PlM")
    p.add_argument("--save-type", type=int, default=0x31)
    args = p.parse_args()

    if args.action == "probe":
        ok, msg = sav.palooz_available()
        print(json.dumps({"ok": ok, "msg": msg}))
        return 0 if ok else 1

    if args.action == "dump_gvas":
        data = Path(args.inp).read_bytes()
        gvas, magic, save_type = sav.decompress_sav(data)
        Path(args.out).write_bytes(gvas)
        print(
            json.dumps(
                {
                    "magic": magic.decode("ascii", errors="replace"),
                    "save_type": save_type,
                    "size": len(gvas),
                }
            )
        )
        return 0

    if args.action == "pack_gvas":
        gvas = Path(args.inp).read_bytes()
        magic = args.magic.encode("ascii")
        out = sav.compress_sav(gvas, magic, args.save_type)
        Path(args.out).write_bytes(out)
        print(json.dumps({"size": len(out), "magic": args.magic}))
        return 0

    data = Path(args.inp).read_bytes()
    if args.action == "read_ints":
        gvas, magic, _ = sav.decompress_sav(data)
        out = {
            "magic": magic.decode("ascii", errors="replace"),
            "CoopPlayerMaxNum": sav.get_int_property(gvas, "CoopPlayerMaxNum"),
            "ServerPlayerMaxNum": sav.get_int_property(gvas, "ServerPlayerMaxNum"),
            "GuildPlayerMaxNum": sav.get_int_property(gvas, "GuildPlayerMaxNum"),
        }
        print(json.dumps(out))
        return 0

    if args.action == "set_coop":
        new_data, report = sav.edit_worldoption_coop(data, args.coop)
        Path(args.out).write_bytes(new_data)
        print(json.dumps(report))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
