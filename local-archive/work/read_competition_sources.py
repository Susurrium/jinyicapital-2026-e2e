import argparse
import json
import sys
import tarfile
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
URLS = {
    "competition": "https://bigquant.com/square/competition/45b41c7a-0ac8-42e9-9fe3-0c33dcfb9bca",
    "getting-started": "https://bigquant.com/wiki/doc/BUxEAZqpLa",
    "download": "https://bigquant.com/wiki/doc/cay6LBmvc1",
}


def read_web(name, section):
    response = requests.get(URLS[name], timeout=45)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    if name == "competition":
        root = soup.select_one(f"#{section}" if section else "main")
        if root is None:
            raise RuntimeError("比赛页面未包含正文 main 元素")
    else:
        root = soup
        for element in root(["script", "style"]):
            element.decompose()
    print(root.get_text("\n", strip=True))


def read_agreement():
    reader = PdfReader(ROOT / "赛事数据保密协议.pdf")
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        content = page.extract_text()
        if not content or not content.strip():
            raise RuntimeError(f"协议第 {index} 页未提取到文本")
        pages.append(content)
    # 核对条款是否可读取，避免输出填写表单中的个人信息。
    print(json.dumps({"pages": len(pages), "text_characters": sum(map(len, pages))}))


def read_archives():
    for path in sorted((ROOT / "data").glob("*.tar.gz")):
        # 只查看首个数据成员，保留原始压缩包，不解压全部数据。
        with tarfile.open(path, "r|gz") as archive:
            for member in archive:
                if member.isfile() and member.name.endswith(".feather"):
                    print(json.dumps({
                        "archive": path.name,
                        "archive_bytes": path.stat().st_size,
                        "first_feather": member.name,
                        "member_bytes": member.size,
                    }, ensure_ascii=False))
                    break
            else:
                raise RuntimeError(f"没有找到 Feather 成员：{path}")


def read_schema():
    sys.path.insert(0, str(ROOT / "work" / "deps"))
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.feather as feather

    path = ROOT / "data" / "cpt_jyc_2026_e2e_bar30m.tar.gz"
    with tarfile.open(path, "r|gz") as archive:
        for member in archive:
            if not member.isfile() or not member.name.endswith(".feather"):
                continue
            with archive.extractfile(member) as source:
                buffer = pa.BufferReader(source.read())
            schema = pa.ipc.open_file(buffer).schema
            buffer.seek(0)
            table = feather.read_table(buffer, columns=["date"])
            print(json.dumps({
                "archive": path.name,
                "member": member.name,
                "schema": str(schema),
                "date_range": pc.min_max(table["date"]).as_py(),
                "rows": table.num_rows,
            }, ensure_ascii=False, default=str))
            return
    raise RuntimeError("30 分钟压缩包没有 Feather 成员")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", choices=[*URLS, "agreement", "archives", "schema"])
    parser.add_argument("--section", choices=["overview", "data", "rule"])
    args = parser.parse_args()
    if args.source == "agreement":
        read_agreement()
    elif args.source == "archives":
        read_archives()
    elif args.source == "schema":
        read_schema()
    else:
        read_web(args.source, args.section)
