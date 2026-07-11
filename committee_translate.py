# -*- coding: utf-8 -*-
"""Committee translation helpers for Congress Monitor 4.
Supports both Senate and House committees.
"""

from __future__ import annotations

import re

SENATE_TRANSLATE = {
    "Aging": "美国参议院老龄委员会",
    "Agriculture, Nutrition, and Forestry": "美国参议院农业、营养和林业委员会",
    "Appropriations": "美国参议院拨款委员会",
    "Armed Services": "美国参议院军事委员会",
    "Banking, Housing, and Urban Affairs": "美国参议院银行、住房和城市事务委员会",
    "Budget": "美国参议院预算委员会",
    "Commerce, Science, and Transportation": "美国参议院商务、科学和运输委员会",
    "Energy and Natural Resources": "美国参议院能源与自然资源委员会",
    "Environment and Public Works": "美国参议院环境与公共工程委员会",
    "Ethics": "美国参议院道德委员会",
    "Finance": "美国参议院财政委员会",
    "Foreign Relations": "美国参议院外交关系委员会",
    "Health, Education, Labor, and Pensions": "美国参议院卫生、教育、劳工和养老金委员会",
    "Homeland Security and Governmental Affairs": "美国参议院国土安全和政府事务委员会",
    "Indian Affairs": "美国参议院印第安事务委员会",
    "Intelligence": "美国参议院情报委员会",
    "Judiciary": "美国参议院司法委员会",
    "Rules and Administration": "美国参议院规则和行政委员会",
    "Small Business and Entrepreneurship": "美国参议院小企业与创业委员会",
    "Veterans' Affairs": "美国参议院退伍军人事务委员会",
    # 特别委员会——特殊命名常见变体
    "Aging (Special)": "美国参议院老龄特别委员会",
    "Special Committee on Aging": "美国参议院老龄特别委员会",
}

HOUSE_TRANSLATE = {
    "Agriculture": "美国众议院农业委员会",
    "Appropriations": "美国众议院拨款委员会",
    "Armed Services": "美国众议院军事委员会",
    "Budget": "美国众议院预算委员会",
    "Education and the Workforce": "美国众议院教育和劳动力委员会",
    "Education and Workforce": "美国众议院教育和劳动力委员会",
    "Energy and Commerce": "美国众议院能源和商业委员会",
    "Ethics": "美国众议院道德委员会",
    "Financial Services": "美国众议院金融服务委员会",
    "Foreign Affairs": "美国众议院外交事务委员会",
    "Homeland Security": "美国众议院国土安全委员会",
    "House Administration": "美国众议院众议院行政委员会",
    "Judiciary": "美国众议院司法委员会",
    "Natural Resources": "美国众议院自然资源委员会",
    "Oversight and Government Reform": "美国众议院监督和政府改革委员会",
    "Oversight and Accountability": "美国众议院监督与问责委员会",
    "Rules": "美国众议院规则委员会",
    "Science, Space, and Technology": "美国众议院科学、太空与技术委员会",
    "Small Business": "美国众议院小企业委员会",
    "Transportation and Infrastructure": "美国众议院交通和基础设施委员会",
    "Veterans' Affairs": "美国众议院退伍军人事务委员会",
    "Ways and Means": "美国众议院筹款委员会",
    # 特别委员会
    "Permanent Select Committee on Intelligence": "美国众议院常设情报特别委员会",
    "Select Committee on the Strategic Competition Between the United States and the Chinese Communist Party": "美国众议院美中战略竞争特别委员会",
    "Select Committee on the Modernization of Congress": "美国众议院国会现代化特别委员会",
    "Intelligence (Permanent Select) Committee": "美国众议院常设情报特别委员会",
    # 不同表达方式的变体
    "House Permanent Select Committee on Intelligence": "美国众议院常设情报特别委员会",
    "House Select Committee on the Strategic Competition Between the United States and the Chinese Communist Party": "美国众议院美中战略竞争特别委员会",
    "Select Committee on Aging": "美国众议院老龄特别委员会",
}

# 主题/短语映射，用于子委员会命名规则
SUBCOMM_TOPIC_TRANSLATE = {
    "Defense": "国防",
    "Cybersecurity": "网络安全",
    "Readiness": "战备",
    "Seapower and Projection Forces": "海权与力量投送",
    "Military Personnel": "军事人事",
    "Intelligence and Special Operations": "情报与特种作战",
    "Oversight and Investigations": "监督与调查",
    "Health": "卫生",
    "Labor, Health and Human Services, Education, and Related Agencies": "劳工、卫生与公众服务、教育及相关机构",
    "Homeland Security": "国土安全",
    "Interior, Environment, and Related Agencies": "内政、环境及相关机构",
    "Financial Services and General Government": "金融服务与综合政府事务",
    "Commerce, Justice, Science, and Related Agencies": "商务、司法、科学及相关机构",
    "State, Foreign Operations, and Related Programs": "国务院、对外行动及相关项目",
    "Legislative Branch": "立法部门",
    "Agriculture, Rural Development, Food and Drug Administration, and Related Agencies": "农业、农村发展、食品药品监督管理局及相关机构",
    "Energy and Water Development": "能源与水资源开发",
    "Transportation, Housing and Urban Development, and Related Agencies": "交通、住房和城市发展及相关机构",
    "National Security": "国家安全",
    "Strategic Forces": "战略力量",
    "Tactical Air and Land Forces": "战术空中与地面力量",
    "Courts, Intellectual Property, Artificial Intelligence, and the Internet": "法院、知识产权、人工智能与互联网",
    "Crime and Federal Government Surveillance": "犯罪与联邦政府监控",
    "Federal Law Enforcement": "联邦执法",
    "Federal Lands": "联邦土地",
    "Water, Wildlife and Fisheries": "水资源、野生动物与渔业",
    "Commodity Markets, Digital Assets, and Rural Development": "大宗商品市场、数字资产与农村发展",
    "General Farm Commodities, Risk Management, and Credit": "一般农产品、风险管理与信贷",
    "Conservation, Research, and Biotechnology": "保护、研究与生物技术",
    "Nutrition and Foreign Agriculture": "营养与国际农业",
    "Livestock, Dairy, and Poultry": "畜牧、乳业与家禽",
}

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()

def normalize_committee_name(name: str) -> str:
    # 最大程度清理常见前缀/后缀，输出主干名
    text = _clean(name)
    prefix_patterns = [
        r"^(United States )?(House|Senate) Committee on ",
        r"^(House|Senate) ",
        r"^Committee (on|for) ",
        r"^Special Committee on ",
        r"^Select Committee on ",
        r"^Permanent Select Committee on ",
        r"^House Committee on ",
        r"^Senate Committee on ",
    ]
    for patt in prefix_patterns:
        text = re.sub(patt, "", text, flags=re.I)
    # 后缀 "Committee", "Subcommittee", "Task Force"
    text = re.sub(r"\s*(Committee|Subcommittee|Task Force)$", "", text, flags=re.I)
    text = text.strip(" -")
    return text

def committee_type_from_name(name: str) -> dict:
    """识别类型,返回dict
    type: main/sub/select/permSelect/special
    main_name/ sub_name
    """
    # 原始
    name = _clean(name)
    lowered = name.lower()
    # - Subcommittee 检测
    subcomm_match = re.search(r"Subcommittee on (.+)", name, flags=re.I)
    if subcomm_match:
        before = name[:subcomm_match.start()].strip(" -")
        main_name = normalize_committee_name(before)
        sub_name = _clean(subcomm_match.group(1))
        return {
            "kind": "subcommittee",
            "main": main_name,
            "sub": sub_name,
            "raw": name,
        }
    # - eg: Cybersecurity, Information Technology, and Government Innovation Subcommittee
    patt2 = re.compile(r"(.+)\sSubcommittee$", re.I)
    m2 = patt2.search(name)
    if m2:
        before = name[:m2.start()].strip(" -")
        main_name = normalize_committee_name(before)
        sub_name = _clean(m2.group(1))
        return {
            "kind": "subcommittee",
            "main": main_name,
            "sub": sub_name,
            "raw": name,
        }
    # - Permanent Select Committee
    if re.search(r"Permanent Select Committee on", name, re.I) or "Permanent Select" in name:
        base_name = normalize_committee_name(name)
        return {
            "kind": "permselect",
            "main": base_name,
            "raw": name
        }
    # - Select Committee
    if re.search(r"Select Committee on", name, re.I):
        base_name = normalize_committee_name(name)
        return {
            "kind": "select",
            "main": base_name,
            "raw": name
        }
    # - Special Committee
    if re.search(r"Special Committee on", name, re.I) or "Special)" in name:
        base_name = normalize_committee_name(name)
        return {
            "kind": "special",
            "main": base_name,
            "raw": name
        }
    # - House/Senate X Committee
    patt3 = re.compile(r"^(House|Senate) (.+) Committee$", re.I)
    m3 = patt3.match(name)
    if m3:
        return {
            "kind": "main",
            "main": m3.group(2),
            "raw": name
        }
    # - eg 'Aging (Special)'
    if re.match(r".+\s?\(Special\)$", name):
        base_name = normalize_committee_name(name.replace("(Special)", ""))
        return {
            "kind": "special",
            "main": base_name,
            "raw": name
        }
    # fallback
    return {
        "kind": "main",
        "main": normalize_committee_name(name),
        "raw": name
    }

def translate_subcommittee_topic(topic: str) -> str:
    cleaned = _clean(topic)
    for k, v in SUBCOMM_TOPIC_TRANSLATE.items():
        if cleaned.lower() == k.lower():
            return v
    # 尝试匹配包含关系
    for k, v in SUBCOMM_TOPIC_TRANSLATE.items():
        if k.lower() in cleaned.lower():
            return v
    # 兜底返回英文主题
    return cleaned

def build_committee_cn(main: str, chamber: str, kind: str = "main", sub: str = "") -> str:
    # 是否为众议院/参议院
    chamber_zh = "众议院" if (chamber and chamber.lower() == "house") else "参议院"
    # 先走主字典映射（命中特殊变体也OK）
    if kind == "main":
        if chamber_zh == "众议院" and main in HOUSE_TRANSLATE:
            return HOUSE_TRANSLATE[main]
        if chamber_zh == "参议院" and main in SENATE_TRANSLATE:
            return SENATE_TRANSLATE[main]
        # 兜底主
        return f"美国{chamber_zh}{main}委员会" if main else ""
    # permselect
    if kind == "permselect":
        if chamber_zh == "众议院" and "Intelligence" in main:
            return "美国众议院常设情报特别委员会"
        return f"美国{chamber_zh}常设{main}特别委员会"
    # select
    if kind == "select":
        # 特殊mapping
        if chamber_zh == "众议院" and "the Strategic Competition Between the United States and the Chinese Communist Party" in main:
            return "美国众议院美中战略竞争特别委员会"
        if chamber_zh == "众议院" and main in HOUSE_TRANSLATE:
            return HOUSE_TRANSLATE[main]
        return f"美国{chamber_zh}特别{main}委员会"
    # special
    if kind == "special":
        if chamber_zh == "参议院" and ("Aging" in main or main in ["Aging"]):
            return "美国参议院老龄特别委员会"
        return f"美国{chamber_zh}{main}特别委员会"
    # subcommittee
    if kind == "subcommittee":
        # 先翻译主委员会
        main_cn = ""
        if chamber_zh == "众议院" and main in HOUSE_TRANSLATE:
            main_cn = HOUSE_TRANSLATE[main]
        elif chamber_zh == "参议院" and main in SENATE_TRANSLATE:
            main_cn = SENATE_TRANSLATE[main]
        else:
            main_cn = f"美国{chamber_zh}{main}委员会"
        # 翻译主题
        sub_cn = translate_subcommittee_topic(sub)
        if sub_cn and sub_cn != sub:
            return f"{main_cn}下属{sub_cn}小组委员会"
        elif sub_cn:
            return f"{main_cn}下属{sub_cn}小组委员会"
        else:
            return f"{main_cn}下属小组委员会"
    # fallback
    return f"美国{chamber_zh}{main}委员会"

def get_committee_cn(name: str, chamber: str | None = None) -> str:
    """优先用字典，有规则再规则化"""
    raw = _clean(name)
    info = committee_type_from_name(raw)
    kind = info.get("kind")
    main = info.get("main", "")
    sub = info.get("sub", "")
    lowchamber = ""
    if chamber:
        lowchamber = chamber.strip().lower()
    # 先优先直接走字典（适配原有特殊case）
    if chamber and lowchamber == "senate":
        if raw in SENATE_TRANSLATE:
            return SENATE_TRANSLATE[raw]
    if chamber and lowchamber == "house":
        if raw in HOUSE_TRANSLATE:
            return HOUSE_TRANSLATE[raw]
    if main in SENATE_TRANSLATE:
        return SENATE_TRANSLATE[main]
    if main in HOUSE_TRANSLATE:
        return HOUSE_TRANSLATE[main]
    if raw in HOUSE_TRANSLATE:
        return HOUSE_TRANSLATE[raw]
    if raw in SENATE_TRANSLATE:
        return SENATE_TRANSLATE[raw]
    # 未命中时规则化命名
    chamber_resolved = chamber if chamber in {"House", "Senate"} else (
        "House" if "House" in raw else ("Senate" if "Senate" in raw else None))
    res = build_committee_cn(main, chamber_resolved or "House", kind=kind, sub=sub)
    return res or raw

def get_committee_en(name: str, chamber: str | None = None) -> str:
    raw = _clean(name)
    # 简单规则，与原来一致
    if raw.startswith("Senate ") or raw.startswith("House "):
        return raw
    base = normalize_committee_name(raw)
    if chamber == "Senate":
        return f"Senate {base} Committee" if base else raw
    if chamber == "House":
        return f"House {base} Committee" if base else raw
    return raw
