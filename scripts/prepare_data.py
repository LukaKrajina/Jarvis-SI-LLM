#!/usr/bin/env python3
"""
prepare_data.py —— Jarvis 训练数据准备：下载 → 清洗 → 分档切分

给模型灵魂张罗一顿大餐，稳住节奏，一步一个脚印。
本人训练用数据源（七位「食材供应商」，各司其职）：
  ① 本地 rvdl 源码（Ravendrel / Chimera / OpenButler，MIT —— 自家珍藏，第一优先级）
  ② 中文维基百科（wikimedia/wikipedia，CC BY-SA 3.0 / GFDL）
  ③ 英文维基百科（wikimedia/wikipedia）
  ④ C4 英文（allenai/c4，ODC-BY）
  ⑤ 代码编程（the-stack-v2 衍生 permissive + codeparrot/github-code）
  ⑥ 科研数据（arXiv 全文，permutans/arxiv-papers-by-subject，MIT）
  ⑦ 轻小说（alpindale/light-novels）——**许可禁止商用**，单独进
     manifest/research_only/，不混入可商用分档

许可分流：仅 commercial_ok=True 的源进入 flash/pro/ultra 分档，
每个源的许可写入 manifest/manifest.json 便于审计。

分档（按 pB 对应数据规模，Chinchilla 式 token:param ≈ 20:1 的务实折算）：
  flash_0.5p / flash_1p / flash_3p
  pro_0.5p  / pro_1p  / pro_3p
  ultra_3p  / ultra_5p

用法：
  python3 prepare_data.py download    # 只下载
  python3 prepare_data.py clean       # 只清洗
  python3 prepare_data.py all         # 下载 + 清洗 + 分档（默认）

环境：仅依赖 Python 标准库 + curl（无第三方库，兼容 Python 3.14，少装一样早开饭）。
"""
import bz2
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(os.environ.get("JARVIS_DATA", "/home/lukakrajina/JarvisLearnData"))
RAW = ROOT / "raw"
CLEAN = ROOT / "clean"
MANIFEST = ROOT / "manifest"

# 分档 → 目标清洗后字节数（务实折算：字节 ≈ 中文 token，≈ 4× 英文 token，目标定得明明白白）
TIERS = {
    "flash_0.5p": 512 * 1024 * 1024,    # 512 MB，轻装上路
    "flash_1p":   1024 * 1024 * 1024,   # 1 GB，稳步前行
    "flash_3p":   3072 * 1024 * 1024,   # 3 GB，小试牛刀
    "pro_0.5p":   512 * 1024 * 1024,
    "pro_1p":     1024 * 1024 * 1024,
    "pro_3p":     3072 * 1024 * 1024,
    "ultra_3p":   3072 * 1024 * 1024,
    "ultra_5p":   5120 * 1024 * 1024,  # 5 GB，全力以赴
}

# ── 下载：把粮食稳稳搬进仓库 ────────────────────────────────────────────────

HF_MIRROR = "https://hf-mirror.com"  # 国内镜像（hf-mirror.com），可经 HF_ENDPOINT 覆盖，顺手的入口

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

_PRINT_LOCK = threading.Lock()


def _log(msg: str) -> None:
    """线程安全打印（并行下载时输出井井有条，谁也不抢话）。"""
    with _PRINT_LOCK:
        print(msg, flush=True)


def curl(url: str, dest: Path) -> bool:
    """curl 下载，带断点续传（掉了链子也能接着跑）。"""
    if dest.exists() and dest.stat().st_size > 0:
        _log(f"  [跳过] 已存在 {dest.name} ({dest.stat().st_size // 1024 // 1024} MB)")
        return True
    _log(f"  [下载] {dest.name}")
    r = subprocess.run(
        ["curl", "-L", "--fail", "--retry", "3", "-C", "-", "-o", str(dest), url],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not dest.exists():
        _log(f"  [失败] {url}: {r.stderr[:200]}")
        return False
    _log(f"  [完成] {dest.name} ({dest.stat().st_size // 1024 // 1024} MB)")
    return True


# ── 下载器：aria2 风格（多任务并发 + 单文件多连接分片）────────────────────────
#
# 为什么忍痛暂别 curl：hf-mirror 对**单连接**限速（实测 ~0.12 MB/s），curl 单进程
# 只占 1 个连接，再多重试也填不满带宽。aria2 的点子很妙：「单文件切成 N 片并发
# Range 请求」+「多文件并发」，把连接数叠上去（aria2c -x/-s 就是这个机制）。
# 本机装 aria2 需要 sudo 交互密码，所以干脆在脚本里亲手实现等价机制：
#   · 单文件：HEAD 拿 Content-Length，切成 ARIA_PARTS 片并发 Range 下载后合并
#   · 多文件：外层 ThreadPoolExecutor 并发 WORKERS 个文件
# 总连接数 ≈ WORKERS × ARIA_PARTS，人多力量大。
# 注：curl() 仍保留，专职负责 hf_ls 的 JSON API 查询（小响应，无下载需求）。

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
ARIA_PARTS = int(os.environ.get("ARIA_PARTS", "8"))   # 每文件分片数（≈ aria2 -s），八仙过海各显神通
MIN_SPLIT_BYTES = 4 * 1024 * 1024                      # <4 MB 不分片（overhead > 收益，小文件单干更省心）


def _fetch_range(url: str, start: int, end: int, part: Path, timeout: int = 180) -> int:
    """下载单个 Range 分片到 part 文件，返回字节数（这点小活，稳稳拿下）。"""
    import requests
    headers = {"User-Agent": UA, "Range": f"bytes={start}-{end}"}
    with requests.get(url, headers=headers, stream=True, timeout=timeout,
                      allow_redirects=True) as r:
        r.raise_for_status()
        with open(part, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                if chunk:
                    f.write(chunk)
    return part.stat().st_size


def aria2_download(url: str, dest: Path, parts: int = 0) -> bool:
    """aria2 风格下载：单文件多连接分片并发（等价 aria2c -x/-s）。

    已存在且非空的文件直接跳过（复用已下数据）。稍有闪失也会把分片与半成品收拾干净，
    不留下会污染「已完成」判断的残缺文件，让下一次出发更清爽。
    """
    import requests
    n = parts or ARIA_PARTS
    # 1) 先 HEAD 拿 Content-Length，才能给已有文件做「完整」体检
    try:
        h = requests.head(url, headers={"User-Agent": UA}, timeout=30, allow_redirects=True)
        total = int(h.headers.get("Content-Length", 0) or 0)
        accept_ranges = (h.headers.get("Accept-Ranges", "") or "").lower() == "bytes"
    except Exception as e:
        _log(f"  [失败] HEAD {url}: {e}")
        return False

    # 2) 已存在校验：只有「大小对得上 Content-Length」才算完成。
    #    被截断的文件（curl 断点续传残留 / 分片合并中断）大小会偏小，温柔地删掉
    #    重下就好 —— 否则会被当成「已存在」跳过，清洗时 pyarrow 报
    #    "Parquet magic bytes not found"（文件尾没有 PAR1 footer）。
    if dest.exists() and dest.stat().st_size > 0:
        if total <= 0 or dest.stat().st_size == total:
            _log(f"  [跳过] 已存在 {dest.name} ({dest.stat().st_size // 1024 // 1024} MB)")
            return True
        _log(f"  [不完整] {dest.name}: {dest.stat().st_size} != {total}，删除重下")
        dest.unlink(missing_ok=True)

    # 3) 不支持 Range / 文件太小 → 单连接整体下载（简单活儿用简单办法）
    if not accept_ranges or total <= 0 or total < MIN_SPLIT_BYTES:
        _log(f"  [下载] {dest.name} (单连接, {total // 1024 // 1024} MB)")
        try:
            with requests.get(url, headers={"User-Agent": UA}, stream=True,
                              timeout=600) as r, open(dest, "wb") as f:
                r.raise_for_status()
                for chunk in r.iter_content(1 << 16):
                    if chunk:
                        f.write(chunk)
            if total > 0 and dest.stat().st_size != total:
                dest.unlink(missing_ok=True)
                _log(f"  [不完整] {dest.name}: {dest.stat().st_size} != {total}")
                return False
            return True
        except Exception as e:
            dest.unlink(missing_ok=True)
            _log(f"  [失败] {dest.name}: {e}")
            return False

    # 3) 分片并发下载（众人拾柴火焰高）
    chunk_size = (total + n - 1) // n
    spans: list[tuple[int, int]] = []
    for i in range(n):
        s = i * chunk_size
        e = min(total - 1, s + chunk_size - 1)
        if s > e:
            break
        spans.append((s, e))
    part_files = [dest.with_name(dest.name + f".part{i}") for i in range(len(spans))]
    _log(f"  [下载] {dest.name} ({total // 1024 // 1024} MB, {len(spans)} 分片并发)")
    try:
        with ThreadPoolExecutor(max_workers=len(spans)) as ex:
            futs = [ex.submit(_fetch_range, url, s, e, p)
                    for (s, e), p in zip(spans, part_files)]
            for f in as_completed(futs):
                f.result()          # 任一分片稍有不顺即抛，交由外层统一收拾
        with open(dest, "wb") as out:      # 合并（合拢拼图）
            for p in part_files:
                with open(p, "rb") as src:
                    shutil.copyfileobj(src, out)
        for p in part_files:
            p.unlink(missing_ok=True)
        if total > 0 and dest.stat().st_size != total:   # 合并后再核对一遍大小
            dest.unlink(missing_ok=True)
            _log(f"  [不完整] {dest.name} 合并后 {dest.stat().st_size} != {total}，删除")
            return False
        _log(f"  [完成] {dest.name} ({dest.stat().st_size // 1024 // 1024} MB)")
        return True
    except Exception as e:
        for p in part_files:
            p.unlink(missing_ok=True)
        dest.unlink(missing_ok=True)
        _log(f"  [失败] {dest.name}: {e}")
        return False


def hf_ls(dataset: str, path: str = "") -> list[tuple[str, int, str]]:
    """HF API 列目录（返回 [(path, size, type)]，type ∈ {file, directory}），一眼看清库存。"""
    url = f"{HF_MIRROR}/api/datasets/{dataset}/tree/main" + (f"/{path}" if path else "")
    # urllib 默认 UA 会被 HF 拒之门外（403），借 curl 带上浏览器 UA 礼貌敲门。
    r = subprocess.run(
        ["curl", "-L", "--fail", "--max-time", "30", "-A",
         "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36", url],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"HF API 查询失败 {url}: {r.stderr[:200]}")
    out = []
    for f in json.loads(r.stdout):
        if isinstance(f, dict):
            out.append((f["path"], f.get("size", 0), f.get("type", "file")))
    return sorted(out)


def _download_paths(dataset: str, files: list[tuple[str, int]], prefix: str,
                    workers: int = 4, name_fn=None) -> int:
    """并行下载一批已知路径的文件。

    并行的理由：hf-mirror 单连接限速明显（实测 ~0.12 MB/s），多连接可叠加吞吐；
    每个文件一个独立 curl 子进程，天然各自为战、互不拖累，还都能断点续传。
    """
    total = 0
    ok = 0

    def one(idx_path):
        i, (path, size) = idx_path
        url = f"{HF_MIRROR}/datasets/{dataset}/resolve/main/{path}"
        if name_fn:
            fname = name_fn(path, i)
        else:
            # 兼容旧命名（3 位补零）：已下好的 shard 直接复用，
            # 免得把十几 GB 白费功夫重下一遍。
            legacy = RAW / f"{prefix}_{i:03d}{Path(path).suffix}"
            fname = (legacy.name if legacy.exists() and legacy.stat().st_size > 0
                     else f"{prefix}_{i:04d}{Path(path).suffix}")
        dest = RAW / fname
        return aria2_download(url, dest), size

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, t) for t in enumerate(files)]
        for fut in as_completed(futs):
            good, size = fut.result()
            if good:
                total += size
                ok += 1
    print(f"  [HF] {prefix}: {ok}/{len(files)} 成功, {total // 1024 // 1024} MB")
    return total


def download_hf(dataset: str, config: str, prefix: str, max_shards: int = 0,
                workers: int = 4):
    """下载 HF 数据集的文件（最多 max_shards 个，0=全部），多线程并行，多条腿赶路。"""
    entries = hf_ls(dataset, config) if config else hf_ls(dataset)
    files = [(p, s) for p, s, t in entries if t == "file"]
    if max_shards > 0:
        files = files[:max_shards]
    print(f"  [HF] {dataset} ({config or 'root'}): {len(files)} 个文件，并行 {workers} 路")
    return _download_paths(dataset, files, prefix, workers)


def download_wikipedia_zh():
    return download_hf("wikimedia/wikipedia", "20231101.zh", "zhwiki", 0)

def download_wikipedia_en(max_shards: int = 41):
    return download_hf("wikimedia/wikipedia", "20231101.en", "enwiki", max_shards)


def copy_local_sources():
    """复制本地 rvdl 源码（MIT，第一优先级、最快的语料），仓库就在手边，顺手抄近路。"""
    srcs = [
        ("Ravendrel", "/mnt/nvme/Project/Ravendrel", [".rvdl", ".cpp", ".hpp", ".h", ".ts", ".md", ".py"]),
        ("Chimera", "/mnt/nvme/Project/Chimera", [".rvdl", ".md", ".py"]),
        ("OpenButler", "/mnt/nvme/Project/OpenButler", [".ts", ".md", ".rvdl", ".cpp", ".hpp"]),
    ]
    total = 0
    for name, root, exts in srcs:
        out = RAW / f"{name.lower()}_src.txt"
        if out.exists():
            total += out.stat().st_size
            continue
        n = 0
        with open(out, "w", encoding="utf-8") as f:
            rp = Path(root)
            if not rp.exists():
                continue
            for p in rp.rglob("*"):
                if ".git" in p.parts or "node_modules" in p.parts or "out" in p.parts or "build" in p.parts:
                    continue
                if p.suffix in exts and p.is_file():
                    try:
                        f.write(p.read_text(encoding="utf-8", errors="ignore") + "\n\n")
                        n += 1
                    except OSError:
                        pass
        total += out.stat().st_size
        print(f"  [源码] {name}: {n} 文件 → {out.name} ({out.stat().st_size // 1024} KB)")
    return total


# ── 新增数据源：代码 / 科研 / 日文轻小说（三张新面孔） ────────────────────────

# 代码：the-stack-v2 的 smollm3 衍生（Stack v2 本身已按 permissive 许可过滤，取之有道）
STACK_SMOLLM3 = "jordangong/the-stack-v2-smollm3"
GITHUB_CODE = "codeparrot/github-code"
# 目录名 → 语言别名（小写归一，兼容 cpp / c++ / c-sharp / c# 等不同写法，包罗万象）
CODE_LANG_ALIASES = {
    "python": "Python", "java": "Java", "c++": "C++", "cpp": "C++", "c": "C",
    "c#": "C-Sharp", "c-sharp": "C-Sharp", "csharp": "C-Sharp",
    "javascript": "JavaScript", "typescript": "TypeScript", "go": "Go",
    "rust": "Rust", "php": "PHP", "ruby": "Ruby", "shell": "Shell",
    "kotlin": "Kotlin", "swift": "Swift", "scala": "Scala", "html": "HTML",
    "css": "CSS", "markdown": "Markdown", "lua": "Lua", "perl": "Perl",
    "dart": "Dart", "r": "R", "julia": "Julia", "haskell": "Haskell",
    "sql": "SQL", "zig": "Zig", "elixir": "Elixir", "elm": "Elm",
    "ocaml": "OCaml", "clojure": "Clojure", "fortran": "Fortran",
    "objective-c": "Objective-C", "groovy": "Groovy", "powershell": "PowerShell",
    "dockerfile": "Dockerfile", "cmake": "CMake", "makefile": "Makefile",
    "assembly": "Assembly", "text": "Text", "tex": "TeX", "vim": "Vim",
    "nix": "Nix", "jupyter-notebooks": "Jupyter", "cuda": "CUDA",
    "verilog": "Verilog", "vhdl": "VHDL", "solidity": "Solidity",
}

# 科研：arXiv 论文全文，按学科 / 年 / 月分片（MIT 许可，可商用），给模型喂点「硬核营养」
ARXIV_BY_SUBJ = "permutans/arxiv-papers-by-subject"
SCIENCE_SUBJECTS = [
    "cs.LG", "cs.AI", "cs.CL", "cs.CV", "cs.SE", "cs.CR", "cs.RO", "cs.DB",
    "cs.DC", "cs.NI", "cs.DS", "stat.ML", "stat.ME", "math.AG", "math.OC",
    "math.PR", "physics", "quant-ph", "cond-mat.stat-mech", "cond-mat.dis-nn",
    "eess.AS", "eess.IV", "astro-ph.GA", "astro-ph.CO", "q-bio.QM",
    "q-bio.PE", "nlin.CD", "hep-th", "gr-qc", "econ.EM",
]


def _lang_of(path: str) -> str:
    """从 smollm3 路径推断语言：data/<Lang>-shards-XXXX-YYYY/<file>，一眼认出「乡音」"""
    parts = path.split("/")
    if len(parts) >= 2:
        return parts[1].split("-shards-")[0]
    return "unknown"


def download_code(files_per_lang: int = 4):
    """代码编程数据：the-stack-v2 衍生（按语言）+ codeparrot/github-code，承包各种编程语法。"""
    total = 0
    print(f"  [代码] {STACK_SMOLLM3}：按语言取前 {files_per_lang} 个文件")
    picked: list[tuple[str, int]] = []
    try:
        dirs = [(p, s) for p, s, t in hf_ls(STACK_SMOLLM3, "data") if t == "directory"]
    except RuntimeError as e:
        print(f"  [代码] 目录查询失败: {e}")
        dirs = []
    by_lang: dict[str, list[str]] = {}
    for p, _ in dirs:
        raw_lang = p.split("/")[-1].split("-shards-")[0]
        key = raw_lang.lower()
        if key in CODE_LANG_ALIASES:
            by_lang.setdefault(CODE_LANG_ALIASES[key], []).append(p)
    print(f"  [代码] 命中语言 {len(by_lang)} 种：{', '.join(sorted(by_lang)[:12])}")
    for lang, dpaths in sorted(by_lang.items()):
        d = sorted(dpaths)[0]
        try:
            fs = [(p, s) for p, s, t in hf_ls(STACK_SMOLLM3, d) if t == "file"]
        except RuntimeError:
            continue
        picked.extend(fs[:files_per_lang])
    print(f"  [代码] 共 {len(picked)} 个文件待下")

    def name_fn(path: str, i: int) -> str:
        return f"code_{_lang_of(path)}_{i:04d}.parquet"

    total += _download_paths(STACK_SMOLLM3, picked, "code", workers=6, name_fn=name_fn)
    # 补充：github-code（大文件，含 README/文档等混合内容，锦上添花）
    total += download_hf(GITHUB_CODE, "data", "ghcode",
                         int(os.environ.get("GHCODE_SHARDS", "12")))
    return total


def download_scientific(months_per_subject: int = 2, files_per_month: int = 40):
    """科研数据：arXiv 论文全文（MIT），按学科取最近年份的若干月份，捡最新鲜的读。"""
    print(f"  [科研] {ARXIV_BY_SUBJ}：{len(SCIENCE_SUBJECTS)} 个学科")
    picked: list[tuple[str, int]] = []
    for subj in SCIENCE_SUBJECTS:
        try:
            years = [p for p, s, t in hf_ls(ARXIV_BY_SUBJ, f"data/{subj}") if t == "directory"]
        except RuntimeError:
            continue
        if not years:
            continue
        for yd in sorted(years, reverse=True)[:1]:
            try:
                months = [p for p, s, t in hf_ls(ARXIV_BY_SUBJ, yd) if t == "directory"]
            except RuntimeError:
                continue
            for md in sorted(months, reverse=True)[:months_per_subject]:
                try:
                    fs = [(p, s) for p, s, t in hf_ls(ARXIV_BY_SUBJ, md) if t == "file"]
                except RuntimeError:
                    continue
                picked.extend(fs[:files_per_month])
    print(f"  [科研] 共 {len(picked)} 个文件待下")
    return _download_paths(ARXIV_BY_SUBJ, picked, "arxiv", workers=6)


# 中文网页语料：Chinese FineWeb Edu（apache-2.0，匿名可下，可商用）。
# 补它的原因：首批语料严重偏英文（实测中文仅 ~9%），而中英 5:5 是既定目标，得给中文补补身子。
CHINESE_WEB = "opencsg/chinese-fineweb-edu"
CHINESE_WEB_DIR = "IndustryCorpus"


def download_chinese_web(max_files: int = 4):
    """下载中文网页语料（apache-2.0，可商用），给中文阵营送粮草。"""
    try:
        files = [(p, s) for p, s, t in hf_ls(CHINESE_WEB, CHINESE_WEB_DIR) if t == "file"]
    except RuntimeError as e:
        print(f"  [中文] 目录查询失败: {e}")
        return 0
    files = sorted(files)[:max_files]
    print(f"  [中文] {CHINESE_WEB}: 取 {len(files)} 个文件")
    return _download_paths(CHINESE_WEB, files, "zhweb", workers=4)


def download_lightnovel():
    """日本轻小说（英译本），给模型来点「轻快的课外阅读」。

    ⚠ 许可：creativeml-openrail-m **明确禁止商用**（openrail 的核心条款就是
    non-commercial）。因此本源单独标记为 research-only，不进可商用分档，各住各的房间。
    """
    url = f"{HF_MIRROR}/datasets/alpindale/light-novels/resolve/main/LightNovels.txt"
    dest = RAW / "lightnovels.txt"
    if not aria2_download(url, dest):
        return 0
    return dest.stat().st_size


def download():
    RAW.mkdir(parents=True, exist_ok=True)
    print("=== ① 本地 rvdl 源码（MIT，最快）===")
    copy_local_sources()
    print("=== ② 中文维基百科（HF 镜像，1.6 GB）===")
    download_wikipedia_zh()
    print("=== ③ 英文维基百科（HF 镜像，11 GB）===")
    download_wikipedia_en(int(os.environ.get("ENWIKI_SHARDS", "41")))
    print("=== ④ C4 英文（HF 镜像，前 10 shard ≈ 3 GB，并行）===")
    download_hf("allenai/c4", "en", "c4en", int(os.environ.get("C4_SHARDS", "10")),
                workers=int(os.environ.get("WORKERS", "4")))
    print("=== ⑤ 代码编程数据（the-stack-v2 衍生 + github-code）===")
    download_code(int(os.environ.get("CODE_FILES_PER_LANG", "4")))
    print("=== ⑥ 科研数据（arXiv 全文，MIT）===")
    download_scientific()
    print("=== ⑦ 日本轻小说（research-only，禁商用）===")
    download_lightnovel()
    print("=== ⑧ 中文网页语料（Chinese FineWeb Edu，apache-2.0，补中英比例）===")
    download_chinese_web(int(os.environ.get("ZHWEB_FILES", "4")))
    # 正常完成标记：守护脚本据此区分「异常中断」与「全部下完」，
    # 有了它，下载一结束就能安心报喜，而不会被当成掉线反复重启。
    (RAW / ".download_done").write_text("ok\n", encoding="utf-8")
    print("下载完成。")


# ── 清洗：淘米洗菜，去粗取精 ────────────────────────────────────────────────

RE_REDIRECT = re.compile(r"#(?:REDIRECT|重定向)\s*\[\[", re.I)
RE_TEMPLATE = re.compile(r"\{\{.*?\}\}", re.DOTALL)
RE_REF = re.compile(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", re.DOTALL)
RE_TAG = re.compile(r"<[^>]+>")
RE_EMPTY = re.compile(r"^\s*$")
RE_PII_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
RE_PII_PHONE = re.compile(r"\b\d{3}[-.]?\d{3,4}[-.]?\d{4}\b")
RE_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# 单行字符上限：超过即放手（见 clean_line 的说明，贪多嚼不烂）
MAX_LINE_CHARS = 20_000
# 单源清洗配额（字节）：洗够就收手，把时间留给更有用的地方
CLEAN_QUOTA = int(os.environ.get("CLEAN_QUOTA_MB", "1500")) * 1024 * 1024
# 单个单元格字符上限：超过即放手（见 _clean_parquet_into 的说明）
MAX_CELL_CHARS = 2_000_000


def clean_line(text: str, code_mode: bool = False) -> str | None:
    """清洗一行：去 PII / 去短行 / 去纯符号。返回 None 表示放手（这一行先告退）。

    code_mode=True 时放宽「短行/词碎」判定——代码行天然短且缩进多，
    按自然语言的规则清洗会委屈有效代码，还是网开一面更贴心。
    """
    text = RE_PII_EMAIL.sub("[EMAIL]", text)
    text = RE_PII_PHONE.sub("[PHONE]", text)
    text = RE_IP.sub("[IP]", text)
    text = text.strip()
    # 超长行（minified JS / base64 内联资源 / 单行巨型数据）既无训练价值，
    # 又会让下面的正则在 MB 级字符串上磨蹭几分钟 —— 干脆爽快放手。实测代码语料里
    # 存在单行数 MB 的 bundle，不截断会让清洗「看起来卡住」（CPU 100% 但不产出）。
    if len(text) > MAX_LINE_CHARS:
        return None
    if len(text) < (1 if code_mode else 8):   # 太短没营养，礼貌谢绝
        return None
    if not code_mode:
        if len(set(text)) < 4:     # 纯重复字符，复读机不欢迎
            return None
        if text.count(" ") / max(len(text), 1) > 0.7:  # 词太碎（表格/索引的碎屑）
            return None
    return text


def clean_wikipedia(bz2_path: Path, out: Path):
    """维基 XML dump → 纯文本（去模板/ref/重定向/标签），扒掉外壳只留干货。"""
    print(f"  [清洗] {bz2_path.name}")
    written = 0
    with bz2.open(bz2_path, "rt", encoding="utf-8", errors="ignore") as src, \
         open(out, "w", encoding="utf-8") as dst:
        for event, elem in ET.iterparse(src, events=("end",)):
            if elem.tag.endswith("text") and elem.text:
                txt = elem.text
                if RE_REDIRECT.search(txt[:200]):
                    elem.clear()
                    continue
                txt = RE_TEMPLATE.sub(" ", txt)
                txt = RE_REF.sub(" ", txt)
                txt = RE_TAG.sub(" ", txt)
                for line in txt.splitlines():
                    c = clean_line(line)
                    if c:
                        dst.write(c + "\n")
                        written += 1
                if written % 100000 == 0:
                    print(f"    {written} 行")
            elem.clear()
    print(f"    {written} 行 → {out.name} ({out.stat().st_size // 1024 // 1024} MB)")


# 文本列优先级（不同数据集列名不同：维基=text、代码=content、论文=abstract/text，按图索骥）
TEXT_COL_PRIORITY = ["text", "content", "code", "full_text", "body",
                     "abstract", "markdown", "article", "response"]


def _pick_text_cols(pf) -> list[str]:
    """按优先级挑 parquet 的文本列；挑不到就取所有 string 列（最多 2 列），总有一款合适。"""
    names = list(pf.schema_arrow.names)
    for pref in TEXT_COL_PRIORITY:
        for n in names:
            if n.lower() == pref:
                return [n]
    strs = [f.name for f in pf.schema_arrow if str(f.type) == "string"]
    return strs[:2]


def _clean_parquet_into(path: Path, dst, code_mode: bool = False) -> int:
    """parquet → 清洗后文本写入 dst，返回写入行数（一步一个脚印）。"""
    import pyarrow.parquet as pq
    written = 0
    pf = pq.ParquetFile(path)
    cols = _pick_text_cols(pf)
    if not cols:
        print(f"    [跳过] {path.name}：未找到文本列")
        return 0
    # batch 小一点：单个代码文件可能上百 MB，batch_size 太大时 to_pydict()
    # 会把整批（256 × 大文件）一口吞进内存，导致 CPU 100% 却长时间不产出，细水长流更好。
    for batch in pf.iter_batches(batch_size=64):
        d = batch.to_pydict()
        n = len(d[cols[0]])
        for i in range(n):
            parts = []
            for c in cols:
                v = d[c][i]
                # 超大单元格（minified bundle / base64 内联资源）在 join 之前
                # 就放手——否则 "\n".join + splitlines 会在上百 MB 的字符串上跑马拉松
                if isinstance(v, str) and v.strip() and len(v) <= MAX_CELL_CHARS:
                    parts.append(v)
            if not parts:
                continue
            txt = "\n".join(parts)
            # PII 替换对整个块做一次，而不是每行 3 次 —— 逐行跑正则是百万行级
            # 语料的主要瓶颈（实测会把清洗拖到 0.2 MB/s），偷个小懒，反而更快。
            txt = RE_PII_EMAIL.sub("[EMAIL]", txt)
            txt = RE_PII_PHONE.sub("[PHONE]", txt)
            txt = RE_IP.sub("[IP]", txt)
            # 逐行 dst.write 在百万短行（HTML/日志类语料）上是主要瓶颈：
            # 每行一次 IO 调用 + 一次字符串拼接。改成「先收集、再批量写」，攒够了一起出手。
            min_len = 1 if code_mode else 8
            kept: list[str] = []
            for line in txt.splitlines():
                n = len(line)
                if n > MAX_LINE_CHARS or n < min_len:
                    continue                     # 长度是 O(1)，先轻轻松松淘汰绝大多数
                line = line.strip()
                if len(line) < min_len:
                    continue
                if not code_mode:
                    # len(set(line)) 对每行构造集合，只对短行做（长行天然够多样）
                    if len(line) < 50 and len(set(line)) < 4:
                        continue
                    if line.count(" ") / max(len(line), 1) > 0.7:
                        continue
                kept.append(line)
            if kept:
                dst.write("\n".join(kept))
                dst.write("\n")
                written += len(kept)
    return written


def _clean_c4_gz_into(path: Path, dst) -> int:
    """C4 的 .json.gz（每行一个 JSON）→ 清洗后文本写入 dst，一行一个，慢慢摘。"""
    import gzip
    written = 0
    with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as src:
        for line in src:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            txt = obj.get("text") if isinstance(obj, dict) else None
            if not isinstance(txt, str):
                continue
            for ln in txt.splitlines():
                c = clean_line(ln)
                if c:
                    dst.write(c + "\n")
                    written += 1
    return written


def _pick_raw(prefix: str) -> list[Path]:
    """取某前缀的 raw 文件；同名新旧两种命名时优先旧的（3 位），避免同一 shard 重复计入，账目清清爽爽。"""
    by_idx: dict[int, Path] = {}
    for p in sorted(RAW.glob(f"{prefix}_*")):
        idx_s = p.stem.split("_")[-1]
        if not idx_s.isdigit():
            continue
        idx = int(idx_s)
        if idx not in by_idx or len(idx_s) == 3:
            by_idx[idx] = p          # 3 位旧命名优先，念旧一点没坏处
    return [by_idx[i] for i in sorted(by_idx)]


def clean():
    CLEAN.mkdir(parents=True, exist_ok=True)
    print("=== 清洗 ===")
    for name, bz2 in [("zh", RAW / "zhwiki.xml.bz2"), ("en", RAW / "enwiki.xml.bz2")]:
        if bz2.exists():
            clean_wikipedia(bz2, CLEAN / f"{name}wiki.txt")
    # 本地源码已基本干净，直接搬到新家
    for src in RAW.glob("*_src.txt"):
        shutil.copy(src, CLEAN / src.name)

    # ── parquet 类语料（维基 / 代码 / 论文）→ 纯文本，褪去外衣 ──
    groups = [
        ("wiki", _pick_raw("zhwiki") + _pick_raw("enwiki"), False),
        ("code", _pick_raw("code"), True),
        ("ghcode", _pick_raw("ghcode"), True),
        ("arxiv", _pick_raw("arxiv"), False),
        ("zhweb", _pick_raw("zhweb"), False),   # 中文网页语料，中英平衡的生力军
    ]
    for tag, files, code_mode in groups:
        if not files:
            continue
        out = CLEAN / f"{tag}.txt"
        if out.exists() and out.stat().st_size > 0:
            print(f"  [跳过] {out.name} 已存在（{out.stat().st_size // 1024 // 1024} MB）")
            continue
        total_lines = 0
        with open(out, "w", encoding="utf-8") as dst:
            for f in files:
                # 配额：单源洗够就停。全量清洗 20+ GB 的语料既慢又远超分档需要
                # （最大档 ultra_5p 只要 5 GB），够用就好，把精力留给更要紧的事。
                if out.stat().st_size >= CLEAN_QUOTA:
                    print(f"  [配额] {tag} 已达 {CLEAN_QUOTA // 1024 // 1024} MB，停止")
                    break
                # 单个文件有点小恙（下载被截断 / 非 parquet）不该拖垮整轮清洗，跳过它继续走
                try:
                    total_lines += _clean_parquet_into(f, dst, code_mode)
                except Exception as e:
                    print(f"    [跳过损坏] {f.name}: {type(e).__name__}: {e}")
        print(f"  [清洗] {tag}: {len(files)} 文件 → {out.name} "
              f"({total_lines} 行, {out.stat().st_size // 1024 // 1024} MB)")

    # ── C4（.json.gz）──（一包一包拆开）
    c4_files = sorted(RAW.glob("c4en_*.gz"))
    if c4_files:
        out = CLEAN / "c4en.txt"
        if not (out.exists() and out.stat().st_size > 0):
            total_lines = 0
            with open(out, "w", encoding="utf-8") as dst:
                for f in c4_files:
                    total_lines += _clean_c4_gz_into(f, dst)
            print(f"  [清洗] c4en: {len(c4_files)} 文件 → {out.name} "
                  f"({total_lines} 行, {out.stat().st_size // 1024 // 1024} MB)")

    # ── 日文轻小说（research-only：许可禁止商用）──（礼貌地放去单独房间）
    ln = RAW / "lightnovels.txt"
    if ln.exists():
        out = CLEAN / "lightnovels.txt"
        if not (out.exists() and out.stat().st_size > 0):
            written = 0
            with open(out, "w", encoding="utf-8") as dst, \
                 open(ln, encoding="utf-8", errors="ignore") as src:
                for line in src:
                    c = clean_line(line)
                    if c:
                        dst.write(c + "\n")
                        written += 1
            print(f"  [清洗] lightnovels: {written} 行 → {out.name} "
                  f"({out.stat().st_size // 1024 // 1024} MB)")
    print("清洗完成。")


# ── 分档：按需装盘，各就各位 ────────────────────────────────────────────────

# 研究专用语料（许可禁止商用）→ 不进可商用分档，单独目录，各归各位
RESEARCH_ONLY = {"lightnovels.txt"}

# 各源许可（写入 manifest.json 便于审计），把清白的来路都记在账上
SOURCE_LICENSES = {
    "wiki.txt":        ("wikimedia/wikipedia (zh+en)", "CC BY-SA 3.0 / GFDL", True),
    "zhwiki.txt":      ("wikimedia/wikipedia (zh)", "CC BY-SA 3.0 / GFDL", True),
    "enwiki.txt":      ("wikimedia/wikipedia (en)", "CC BY-SA 3.0 / GFDL", True),
    "c4en.txt":        ("allenai/c4 (en)", "ODC-BY 1.0", True),
    "code.txt":        ("the-stack-v2 衍生 (smollm3)", "permissive (Stack v2 已过滤)", True),
    "ghcode.txt":      ("codeparrot/github-code", "GitHub 各仓库许可混合", True),
    "arxiv.txt":       ("permutans/arxiv-papers-by-subject", "MIT", True),
    "zhweb.txt":       ("opencsg/chinese-fineweb-edu", "Apache-2.0", True),
    # 本地三个仓库的源码：项目自身是 MIT，可商用（此前误标为 unknown/不可商用，现已拨乱反正）
    "chimera_src.txt":    ("本地 Chimera 源码", "MIT", True),
    "openbutler_src.txt": ("本地 OpenButler 源码", "MIT", True),
    "ravendrel_src.txt":  ("本地 Ravendrel 源码", "MIT", True),
    "lightnovels.txt": ("alpindale/light-novels", "creativeml-openrail-m", False),
}


def tier():
    """把 clean/ 下的文本按分档切分到各档目录（Ultra 全量，Flash 最小子集，各得其份）。"""
    print("=== 分档切分 ===")
    all_files = sorted(CLEAN.glob("*.txt"))
    if not all_files:
        print("  无清洗后的文本，先运行 clean。")
        return

    # 许可分流：禁止商用的语料不进可商用分档，界限清晰才走得安心
    files = [f for f in all_files if f.name not in RESEARCH_ONLY]
    research = [f for f in all_files if f.name in RESEARCH_ONLY]
    if research:
        print(f"  [许可] {len(research)} 个研究专用源（禁止商用）单独存放："
              f"{', '.join(f.name for f in research)}")

    # 合并所有文本到统一流（按字节序），中英 5:5 已由「zh/en 维基各半」天然保证，一碗水端平
    total = sum(f.stat().st_size for f in files)
    sizes = {f: f.stat().st_size for f in files}

    # 语言分组：中英 5:5 是既定目标，但各源体量悬殊（英文 30+ GB、中文一度
    # 只有维基里的一小部分），按源平均会把中文稀释掉。所以先按语言分两大组，
    # 各占一半，组内再按源等权分配，人人都有一席之地。
    #
    # 注：wiki.txt 是 zhwiki + enwiki 合并、以英文为主（实测中文仅 8%），
    # 故归入英文侧；中文侧由 zhweb（Chinese FineWeb Edu，纯中文）承担重任。
    ZH_SOURCES = {"zhweb.txt"}
    zh_files = [f for f in files if f.name in ZH_SOURCES]
    en_files = [f for f in files if f.name not in ZH_SOURCES]
    if zh_files:
        print(f"  [语言] 中文源: {', '.join(f.name for f in zh_files)}；"
              f"英文源: {len(en_files)} 个")

    tiers_desc = sorted(TIERS.items(), key=lambda kv: -kv[1])
    for name, target in tiers_desc:
        outdir = MANIFEST / name
        outdir.mkdir(parents=True, exist_ok=True)
        want = min(target, total)

        # 组内等权分配 + 剩余额度补给有余量的源，谁也不亏待
        def allocate(group: list[Path], quota: int) -> dict:
            if not group or quota <= 0:
                return {}
            a = {f: min(quota // len(group), sizes[f]) for f in group}
            rem = quota - sum(a.values())
            while rem > 0:
                added = False
                for f in group:
                    if rem <= 0:
                        break
                    room = sizes[f] - a[f]
                    if room > 0:
                        take = min(room, rem)
                        a[f] += take
                        rem -= take
                        added = True
                if not added:
                    break
            return a

        zh_quota = want // 2
        en_quota = want - zh_quota
        alloc = {}
        alloc.update(allocate(zh_files, zh_quota))
        alloc.update(allocate(en_files, en_quota))

        acc = 0
        with open(outdir / "train.txt", "w", encoding="utf-8") as dst:
            for f in files:
                quota = alloc.get(f, 0)
                if quota <= 0:
                    continue
                written = 0
                # 流式分块读写：一次 read 整个配额会把几 GB 塞进内存，细水长流更从容
                with open(f, encoding="utf-8", errors="ignore") as src:
                    while written < quota:
                        chunk = src.read(min(1 << 20, quota - written))
                        if not chunk:
                            break
                        nb = len(chunk.encode("utf-8"))
                        if written + nb > quota:       # 按字节配额截断最后一块，收放自如
                            keep = max(1, int(len(chunk) * (quota - written) / max(nb, 1)))
                            chunk = chunk[:keep]
                            nb = len(chunk.encode("utf-8"))
                        dst.write(chunk)
                        written += nb
                acc += written
        mix = ", ".join(f"{f.stem} {alloc[f] // 1024 // 1024}MB"
                        for f in files if alloc.get(f, 0) > 0)
        print(f"  {name}: {acc // 1024 // 1024} MB → {outdir / 'train.txt'}")
        print(f"      配比: {mix}")

    # 研究专用（禁止商用）单独出一份，不混入可商用分档，清清爽爽
    if research:
        rdir = MANIFEST / "research_only"
        rdir.mkdir(parents=True, exist_ok=True)
        with open(rdir / "train.txt", "wb") as dst:
            for f in research:
                with open(f, "rb") as src:
                    shutil.copyfileobj(src, dst)
        rbytes = sum(f.stat().st_size for f in research)
        print(f"  research_only: {rbytes // 1024 // 1024} MB → {rdir / 'train.txt'}")

    # manifest 清单（含每个源的许可，便于审计），给每条数据发张「身份证」
    def meta(fname: str):
        return SOURCE_LICENSES.get(fname, ("unknown", "unknown", False))

    with open(MANIFEST / "manifest.json", "w", encoding="utf-8") as m:
        json.dump({
            "total_bytes": total,
            "tiers": {k: {"bytes": v, "tokens_est": v // 2} for k, v in TIERS.items()},
            "sources": [
                {
                    "file": f.name,
                    "bytes": f.stat().st_size,
                    "source": meta(f.name)[0],
                    "license": meta(f.name)[1],
                    "commercial_ok": meta(f.name)[2],
                }
                for f in all_files
            ],
            "research_only": [f.name for f in research],
        }, m, indent=2, ensure_ascii=False)
    print(f"  总文本 {total // 1024 // 1024} MB，清单已写 manifest/manifest.json")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("download", "all"):
        download()
    if cmd in ("clean", "all"):
        clean()
    if cmd in ("tier", "all"):
        tier()
    print("完成。")


if __name__ == "__main__":
    main()