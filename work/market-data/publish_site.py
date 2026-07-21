#!/usr/bin/env python3
import json
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "outputs"
TARGET = Path("/tmp/quant-site-public")


def copy_dir(name):
    source = SOURCE / name
    target = TARGET / name
    if not source.exists():
        raise SystemExit(f"缺少发布目录：{source}")
    shutil.copytree(source, target)


def main():
    if TARGET.exists():
        if TARGET.name != "quant-site-public":
            raise SystemExit(f"拒绝清理异常目录：{TARGET}")
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True, exist_ok=True)
    copy_dir("quant-dual-market-site")
    copy_dir("daily-quant")
    manifest = {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "source": "outputs",
        "target": "public-dashboard",
        "url": "http://127.0.0.1:4174/quant-dual-market-site/",
    }
    (TARGET / "publish-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
