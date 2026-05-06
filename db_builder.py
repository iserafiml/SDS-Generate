#!/usr/bin/env python3
"""
db_builder.py — 从 PubChem 批量构建 raw_material_db.json 条目

数据来源:
  · PubChem REST API — GHS 分类、H/P 码、图形符号、信号词（免费，无需注册）
  · ghs_triggers 阈值 — 依据 GHS Purple Book 第3章混合物分类截断值自动推算

使用方法:
    # 从文件批量处理（推荐）
    python3 db_builder.py --input cas_input.txt --output data/new_entries.json

    # 测试几个 CAS 号
    python3 db_builder.py --cas 7722-84-1 7664-93-9 7647-01-0

    # 处理完毕后直接合并到主数据库
    python3 db_builder.py --input cas_input.txt --merge data/raw_material_db.json

输入文件格式（每行一条，CAS 号在前，名称可选）:
    7722-84-1   Hydrogen Peroxide 50%
    7664-93-9   Sulfuric Acid
    7647-01-0
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# GHS 混合物截断值 (GHS Purple Book Rev.9 Table 3.x cut-off values)
# 映射: H 码 → (hazard_class_key, category, threshold_pct)
# threshold_pct = 该成分在混合物中触发该分类的最低浓度%
# ---------------------------------------------------------------------------
_H_TO_TRIGGER: dict[str, tuple[str, str, float]] = {
    # 氧化性液体 (无标准截断值，使用保守值 1%)
    "H271": ("oxidizing_liquid", "1",  1.0),
    "H272": ("oxidizing_liquid", "2",  1.0),

    # 易燃液体 (混合物用闪点法；此处用保守浓度阈值作为近似)
    "H224": ("flammable_liquid", "1", 10.0),
    "H225": ("flammable_liquid", "2", 10.0),
    "H226": ("flammable_liquid", "3", 10.0),
    "H227": ("flammable_liquid", "4", 10.0),

    # 金属腐蚀
    "H290": ("corrosive_to_metals", "1", 1.0),

    # 皮肤腐蚀/刺激
    "H314": ("skin_corrosion", "1",  1.0),   # 腐蚀 Cat 1 (1A/1B/1C)
    "H315": ("skin_corrosion", "2",  3.0),   # 刺激 Cat 2

    # 眼损伤
    "H318": ("serious_eye_damage", "1", 1.0),  # 严重眼损伤 Cat 1
    "H319": ("serious_eye_damage", "2", 3.0),  # 眼刺激 Cat 2

    # STOT 单次接触
    "H370": ("stot_se", "1", 1.0),
    "H371": ("stot_se", "2", 1.0),
    "H335": ("stot_se", "3", 20.0),

    # 急性毒性 - 经口
    "H300": ("acute_toxicity_oral", "1", 0.1),
    "H301": ("acute_toxicity_oral", "2", 0.1),
    "H302": ("acute_toxicity_oral", "3", 1.0),

    # 急性毒性 - 吸入
    "H330": ("acute_toxicity_inh", "1", 0.1),
    "H331": ("acute_toxicity_inh", "2", 0.1),
    "H332": ("acute_toxicity_inh", "3", 1.0),

    # 水环境危害
    "H400": ("environmental", "1",  0.1),
    "H410": ("environmental", "1",  0.1),
    "H411": ("environmental", "2",  1.0),
    "H412": ("environmental", "3", 10.0),
    "H413": ("environmental", "4", 10.0),
}

# PubChem 图形符号文字 → GHS 编码
_PICTOGRAM_LOOKUP: dict[str, str] = {
    "Flame Over Circle":    "GHS03",
    "Flame":                "GHS02",
    "Corrosion":            "GHS05",
    "Skull and Crossbones": "GHS06",
    "Exclamation Mark":     "GHS07",
    "Health Hazard":        "GHS08",
    "Environment":          "GHS09",
    "Exploding Bomb":       "GHS01",
    "Gas Cylinder":         "GHS04",
}

_NOT_AVAIL = "Not determined or not available."

# ---------------------------------------------------------------------------
# PubChem API helpers
# ---------------------------------------------------------------------------

def _get(session: requests.Session, url: str, timeout: int = 20) -> dict | None:
    try:
        r = session.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def fetch_cid(cas: str, session: requests.Session) -> int | None:
    """CAS → PubChem CID."""
    data = _get(session,
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
        f"{requests.utils.quote(cas)}/cids/JSON")
    if data:
        cids = data.get("IdentifierList", {}).get("CID", [])
        return cids[0] if cids else None
    return None


def fetch_name(cid: int, session: requests.Session) -> str:
    """从 PubChem 获取首选通用名。"""
    data = _get(session,
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/synonyms/JSON")
    if data:
        syns = (data.get("InformationList", {})
                    .get("Information", [{}])[0]
                    .get("Synonym", []))
        return syns[0] if syns else ""
    return ""


def fetch_ghs(cid: int, session: requests.Session) -> dict:
    """从 PubChem pug_view 获取 GHS 分类数据。"""
    result: dict = {"h_codes": [], "p_codes": [], "pictograms": [], "signal_word": ""}
    data = _get(session,
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON"
        f"?heading=GHS+Classification")
    if not data:
        return result

    sections = data.get("Record", {}).get("Section", [])
    ghs_sec = _find_section(sections, "GHS Classification")
    if not ghs_sec:
        return result

    for info in ghs_sec.get("Information", []):
        name = info.get("Name", "")
        val  = info.get("Value", {})
        items = val.get("StringWithMarkup", [])

        if "Hazard Statement" in name:
            # Each item: {"String": "H314: Causes severe skin burns...", ...}
            for item in items:
                text = item.get("String", "").strip()
                code = text.split(":")[0].strip().split()[0]
                if code.startswith("H") and code not in result["h_codes"]:
                    result["h_codes"].append(code)

        elif "Precautionary Statement" in name:
            # All P codes in one comma-separated string: "P260, P261, P301+P330+P331, ..."
            for item in items:
                for token in item.get("String", "").split(","):
                    code = token.strip().split()[0].split("+")[0]
                    if code.startswith("P") and code not in result["p_codes"]:
                        result["p_codes"].append(code)

        elif "Pictogram" in name:
            # GHS code embedded in SVG URL: ".../GHS04.svg" in Markup list
            for item in items:
                for markup in item.get("Markup", []):
                    url = markup.get("URL", "")
                    if "/ghs/" in url and url.endswith(".svg"):
                        code = url.rsplit("/", 1)[-1].replace(".svg", "").upper()
                        if code.startswith("GHS") and code not in result["pictograms"]:
                            result["pictograms"].append(code)

        elif name == "Signal" and not result["signal_word"]:
            if items:
                result["signal_word"] = items[0].get("String", "")

    return result


def fetch_toxicology(cid: int, session: requests.Session) -> dict:
    """从 PubChem 提取 LD50/LC50 数据（尽力而为）。"""
    result: dict = {}
    data = _get(session,
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON"
        f"?heading=Acute+Effects")
    if not data:
        return result

    sections = data.get("Record", {}).get("Section", [])
    acute_sec = _find_section(sections, "Acute Effects")
    if not acute_sec:
        return result

    texts: list[str] = []
    for info in acute_sec.get("Information", []):
        for sv in info.get("StringValueList", []):
            texts.append(sv.strip())

    for text in texts:
        lower = text.lower()
        if "ld50" in lower and "oral" in lower and "rat" in lower and "oral_ld50" not in result:
            result["oral_ld50"] = {"route": "oral", "species": "Rat", "result": _trim(text)}
        elif "lc50" in lower and "rat" in lower and "inhalation_lc50" not in result:
            result["inhalation_lc50"] = {"route": "inhalation", "species": "Rat", "result": _trim(text)}
        elif "ld50" in lower and "dermal" in lower and "dermal_ld50" not in result:
            result["dermal_ld50"] = {"route": "dermal", "species": "Rabbit", "result": _trim(text)}

    return result


def _find_section(sections: list, heading: str) -> dict | None:
    for sec in sections:
        if sec.get("TOCHeading") == heading:
            return sec
        found = _find_section(sec.get("Section", []), heading)
        if found:
            return found
    return None


def _trim(text: str, max_len: int = 200) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text


# ---------------------------------------------------------------------------
# ghs_triggers 推算
# ---------------------------------------------------------------------------

def h_codes_to_triggers(h_codes: list[str]) -> dict:
    """
    将 H 码列表转换为 ghs_triggers 字典。
    同一 hazard_class 保留最严重（阈值最低）的条目。
    """
    best: dict[str, tuple[str, float]] = {}
    for code in h_codes:
        entry = _H_TO_TRIGGER.get(code)
        if not entry:
            continue
        class_key, category, threshold = entry
        if class_key not in best or threshold < best[class_key][1]:
            best[class_key] = (category, threshold)
    return {
        k: {"threshold_pct": v[1], "category": v[0]}
        for k, v in best.items()
    }


# ---------------------------------------------------------------------------
# 主构建函数
# ---------------------------------------------------------------------------

def build_entry(cas: str, hint_name: str, session: requests.Session,
                rm_numbers: list[str] | None = None) -> dict | None:
    """为一个 CAS 号构建完整的 raw_material_db.json 条目。"""

    print(f"  → 查找 CID ...", end=" ", flush=True)
    cid = fetch_cid(cas, session)
    if not cid:
        print("❌ PubChem 未找到")
        return None
    print(f"CID {cid}")
    time.sleep(0.4)

    print(f"  → 获取名称 ...", end=" ", flush=True)
    name = hint_name or fetch_name(cid, session) or cas
    print(name)
    time.sleep(0.4)

    print(f"  → 获取 GHS 数据 ...", end=" ", flush=True)
    ghs = fetch_ghs(cid, session)
    print(f"{len(ghs['h_codes'])} H码  {len(ghs['p_codes'])} P码  "
          f"信号词: {ghs['signal_word'] or '—'}")
    time.sleep(0.4)

    print(f"  → 获取毒理数据 ...", end=" ", flush=True)
    tox = fetch_toxicology(cid, session)
    print(f"{len(tox)} 条记录")
    time.sleep(0.4)

    triggers = h_codes_to_triggers(ghs["h_codes"])

    return {
        "cas":          cas,
        "name":         name,
        "rm_numbers":   rm_numbers or [],
        "ghs_triggers": triggers,

        # ── 需要手动补充 ──────────────────────────────────────────────────
        # oels: 参考 NIOSH Pocket Guide (https://www.cdc.gov/niosh/npg/)
        # 或 ACGIH TLV Booklet，填写格式见现有数据库条目
        "oels": [],

        "toxicology": tox,

        # aquatic_toxicology: 参考 PubChem "Ecotoxicity" 页面或供应商 SDS
        "aquatic_toxicology": {"acute": [], "chronic": []},

        # 以下三项参考供应商 SDS Section 12
        "persistence":     "",
        "bioaccumulation": "",
        "mobility":        "",

        # 致癌性：参考 IARC (https://monographs.iarc.who.int/) 和 NTP RoC
        "iarc_classification": "Not Applicable",
        "ntp_classification":  "Not Applicable",

        # 法规合规：参考 EPA ECHO (https://echo.epa.gov/)
        # TSCA: https://www.epa.gov/tsca-inventory
        # SARA: https://www.epa.gov/epcra/sara-title-iii-section-302-extremely-hazardous-substances
        "regulatory": {
            "tsca_listed":      True,    # ← 待核实
            "sara_302":         False,
            "sara_302_tpq_lbs": "",
            "sara_313":         False,
            "cercla_listed":    False,
            "cercla_rq_lbs":    "",
            "rcra_code":        "",
            "caa_112r":         False,
            "prop_65":          False,
            "prop_65_warning":  "",
            "rtk_states":       [],
        },

        # ── 审核辅助字段（验证完成后可删除）────────────────────────────────
        "_review": {
            "pubchem_cid":   cid,
            "h_codes":       ghs["h_codes"],
            "p_codes":       ghs["p_codes"],
            "pictograms":    ghs["pictograms"],
            "signal_word":   ghs["signal_word"],
            "verified":      False,   # 人工核实后改为 True
        },
    }


# ---------------------------------------------------------------------------
# 输入文件解析
# ---------------------------------------------------------------------------

def load_cas_file(path: str) -> list[tuple[str, str, str]]:
    """
    解析 CAS 列表文件，返回 [(rm, cas, name), ...] 列表。

    支持两种格式（自动识别）：
      · 三列格式（新）：  RM0001<tab>7722-84-1<tab>Hydrogen Peroxide
      · 两列格式（旧）：  7722-84-1<tab>Hydrogen Peroxide
      · 单列格式：        7722-84-1

    以 # 开头的行忽略。多 CAS（含分号）条目跳过。
    """
    entries: list[tuple[str, str, str]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            # 判断是否为三列（第一列是 RM 编号）
            if len(parts) >= 3 and parts[0].upper().startswith("RM"):
                rm  = parts[0].strip()
                cas = parts[1].strip().rstrip(";")
                name = parts[2].strip()
            elif len(parts) >= 2 and parts[0].upper().startswith("RM"):
                rm  = parts[0].strip()
                cas = parts[1].strip().rstrip(";")
                name = ""
            else:
                # 旧格式：CAS [name]
                rm = ""
                cas_parts = parts[0].split(None, 1)
                cas = cas_parts[0].strip().rstrip(";")
                name = (parts[1].strip() if len(parts) > 1
                        else (cas_parts[1].strip() if len(cas_parts) > 1 else ""))

            if ";" in cas or cas.lower() in ("not", "non-haz"):
                continue
            entries.append((rm, cas, name))
    return entries


# ---------------------------------------------------------------------------
# 文件 I/O
# ---------------------------------------------------------------------------

def _load_existing(path: Path) -> dict[str, dict]:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return {e["cas"]: e for e in json.load(f)}
    return {}


def _save(entries: dict[str, dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(entries.values()), f, indent=2, ensure_ascii=False)


def _merge_into_db(new_entries: dict[str, dict], db_path: Path) -> None:
    """将新条目合并进现有 raw_material_db.json（不覆盖已有条目，但更新 rm_numbers）。"""
    existing: list[dict] = []
    if db_path.exists():
        with open(db_path, encoding="utf-8") as f:
            existing = json.load(f)
    existing_by_cas: dict[str, dict] = {e["cas"]: e for e in existing}

    added = 0
    for entry in new_entries.values():
        cas = entry["cas"]
        clean = {k: v for k, v in entry.items() if k != "_review"}
        if cas not in existing_by_cas:
            existing_by_cas[cas] = clean
            added += 1
        else:
            # 仅补充 rm_numbers（不覆盖其他已有字段）
            existing_rms = set(existing_by_cas[cas].get("rm_numbers", []))
            new_rms = set(clean.get("rm_numbers", []))
            merged = sorted(existing_rms | new_rms)
            if merged:
                existing_by_cas[cas]["rm_numbers"] = merged

    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(list(existing_by_cas.values()), f, indent=2, ensure_ascii=False)
    print(f"✓ 已合并 {added} 条新记录到 {db_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="从 PubChem 批量构建 raw_material_db.json 条目",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input",  "-i", help="CAS 列表文件路径（每行一条）")
    parser.add_argument("--cas",    "-c", nargs="+", help="直接指定 CAS 号（空格分隔）")
    parser.add_argument("--output", "-o", default="data/new_entries.json",
                        help="输出文件路径（默认: data/new_entries.json）")
    parser.add_argument("--merge",  "-m",
                        help="处理完毕后合并进指定数据库文件（如 data/raw_material_db.json）")
    parser.add_argument("--delay",  "-d", type=float, default=0.5,
                        help="每次 API 请求间隔秒数（默认 0.5，遵守 PubChem 限速）")
    args = parser.parse_args()

    if not args.input and not args.cas:
        parser.print_help()
        sys.exit(1)

    # 组合原始条目
    raw_entries: list[tuple[str, str, str]] = []   # (rm, cas, name)
    if args.input:
        raw_entries = load_cas_file(args.input)
    if args.cas:
        raw_entries += [("", c, "") for c in args.cas]

    # 按 CAS 去重，收集 RM 号列表和首选名称
    cas_to_rms:  dict[str, list[str]] = {}
    cas_to_name: dict[str, str] = {}
    rm_index:    dict[str, dict] = {}   # RM → {cas, name}

    for rm, cas, name in raw_entries:
        if cas not in cas_to_rms:
            cas_to_rms[cas]  = []
            cas_to_name[cas] = name
        if rm and rm not in cas_to_rms[cas]:
            cas_to_rms[cas].append(rm)
        if rm:
            rm_index[rm] = {"cas": cas, "name": name}

    unique_pairs = [(cas, cas_to_name[cas], cas_to_rms[cas])
                    for cas in cas_to_rms]

    out_path = Path(args.output)
    results = _load_existing(out_path)
    if results:
        print(f"已加载 {len(results)} 条缓存记录（继续上次进度）")

    # 写入 rm_index.json（同目录下）
    rm_index_path = out_path.parent / "rm_index.json"
    with open(rm_index_path, "w", encoding="utf-8") as f:
        json.dump(rm_index, f, indent=2, ensure_ascii=False)
    print(f"✓ RM 索引已写入 {rm_index_path}（{len(rm_index)} 条）")

    session = requests.Session()
    session.headers["User-Agent"] = "SDS-Generator-DB-Builder/1.0 (research)"

    failed: list[str] = []
    total = len(unique_pairs)

    print(f"\n共 {total} 个唯一 CAS 号待处理\n{'─' * 50}")

    for i, (cas, hint_name, rm_nums) in enumerate(unique_pairs, 1):
        if cas in results:
            # 缓存命中时也更新 rm_numbers（可能新增了 RM 编号）
            existing_rms = set(results[cas].get("rm_numbers", []))
            merged = sorted(existing_rms | set(rm_nums))
            results[cas]["rm_numbers"] = merged
            print(f"[{i:3d}/{total}] {cas}  ← 已缓存，跳过")
            continue

        print(f"[{i:3d}/{total}] {cas}  {hint_name}  "
              f"[{', '.join(rm_nums) if rm_nums else '无RM'}]")
        try:
            entry = build_entry(cas, hint_name, session, rm_numbers=rm_nums)
            if entry:
                results[cas] = entry
                _save(results, out_path)      # 增量保存，防止中途崩溃丢失进度
            else:
                failed.append(cas)
        except KeyboardInterrupt:
            print("\n用户中断，保存当前进度...")
            _save(results, out_path)
            sys.exit(0)
        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append(cas)

        time.sleep(args.delay)

    _save(results, out_path)

    if args.merge:
        _merge_into_db(results, Path(args.merge))
        # 同时把 rm_index.json 复制到 data/ 目录
        rm_index_dest = Path(args.merge).parent / "rm_index.json"
        with open(rm_index_dest, "w", encoding="utf-8") as f:
            json.dump(rm_index, f, indent=2, ensure_ascii=False)
        print(f"✓ RM 索引已写入 {rm_index_dest}")

    # 汇总报告
    success = len(results)
    print(f"\n{'='*50}")
    print(f"完成！共处理 {total} 条，成功 {success} 条，失败/未找到 {len(failed)} 条")
    print(f"输出文件: {out_path}")
    if failed:
        print(f"未找到的 CAS: {', '.join(failed)}")

    print("""
后续人工核实清单:
  1. 检查每条记录的 _review.h_codes，确认 GHS 分类符合实际
  2. 检查 ghs_triggers 阈值是否适合你的产品浓度范围
  3. 填写 oels（参考 NIOSH Pocket Guide: https://www.cdc.gov/niosh/npg/）
  4. 填写 aquatic_toxicology（参考供应商 SDS Section 12）
  5. 核实 regulatory 字段（TSCA/SARA/Prop65 等）
  6. 核实完成后将 _review.verified 改为 true
  7. 合并进主数据库前删除 _review 字段
""")


if __name__ == "__main__":
    main()
