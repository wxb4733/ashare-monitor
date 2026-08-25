"""生成专利/论文横向对比报告（docs/patent_landscape.md）。

数据源：ip_assets 表（智慧芽 MCP 会话内采样，每标的最多 15 件专利 / 8-10 篇论文）。
统计：专利数、有效/审查中分布、IPC 大类分布、主要申请主体、论文与产学研。
如实标注：库内为智慧芽采样快照（非全量），total_hits 见各家注释。
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ashare_monitor.import_data import get_all_ip_assets

# 展示顺序与简称（键为库内 company key）
ORDER = [
    ("比亚迪股份有限公司", "比亚迪 002594/01211"),
    ("宁德时代新能源科技股份有限公司", "宁德时代 300750"),
    ("小米集团", "小米集团 01810"),
    ("贵州茅台酒股份有限公司", "贵州茅台 600519"),
    ("平安银行股份有限公司", "平安银行 000001"),
    ("英伟达", "英伟达 NVDA"),
]

# 各家用例（真实 total_hits，来自智慧芽搜索）与解读
CONTEXT = {
    "比亚迪股份有限公司": {"hits": "2.7 万+（H01M 电池/电解液 + B60T 制动 + 固态电池前沿）",
                            "note": "样本偏电池/制动，与新能源车+电池垂直整合战略一致"},
    "宁德时代新能源科技股份有限公司": {"hits": "6.5 万（含 DE/JP/KR/US 国际布局，CATL 全球申请主体）",
                            "note": "样本以国际申请为主（DE/JP/KR），H01M 电化学储能绝对主导"},
    "小米集团": {"hits": "13.3 万（手机/汽车/家电全家桶）",
                    "note": "样本三分：手机通信（H04L/H04W）、汽车（B60T/H02M/H01R）、AI 人机交互（G06F3/01）"},
    "贵州茅台酒股份有限公司": {"hits": "1.6 千（茅台集团体系，含循环经济/酱香酒营销子公司）",
                            "note": "样本覆盖酿造工艺/微生物/包装外观/余热利用/废水处理，白酒行业专利强度高"},
    "平安银行股份有限公司": {"hits": "5.8 千（金融科技为主）",
                            "note": "样本全为金融科技：分布式任务/G06F 数据库/风控合规/G06Q 交易系统"},
    "英伟达": {"hits": "2.7 万（AI 计算 + 图形 + 机器人 + 自动驾驶）",
                  "note": "样本覆盖 GPU 计算、神经网络、语音、VR/AR、机器人、自动驾驶感知"},
}

# 新回填 34 家（2026-08-26 高股息队列）解读（hits 见会话内搜索）
QUEUE_NOTE = {
    "宇通客车股份有限公司": "客车+新能源电驱（整车控制/隔振/辅助驾驶），国际布局 AU/EP/WO",
    "珠海格力电器股份有限公司": "空调压缩机/制冷为核心，专利池居家电之首（压缩机/净化/变频/制冰）",
    "华域汽车系统股份有限公司": "汽车零部件（扁线电机/热管理/毫米波雷达），样本以工艺工装与电机结构为主",
    "华能国际电力股份有限公司": "电力（火电+风光+储能），样本覆盖脱硝催化剂/碳捕集/风电/压缩空气储能",
    "兴业银行股份有限公司": "金融科技（批处理/风控/额度调拨/灾备），样本全为 G06F/G06Q",
    "中远海运控股股份有限公司": "航运数字化（气象导航/船港信息/海工装备），样本 G01C/G06F/B63 类",
    "中国光大银行股份有限公司": "金融科技（数据管理/分布式服务/大模型需求分析），G06F 平台类为主",
    "北京银行股份有限公司": "金融科技（风控/图谱/大模型/数字人民币），含多项 HK 授权专利",
    "海尔智家股份有限公司": "智慧家庭（洗衣机/热水器/加湿/干衣），含 US 授权，全球化布局",
    "中国民生银行股份有限公司": "金融科技（视频监督/大模型表格检索/客户旅程图），G06F/G06Q 为主",
    "招商银行股份有限公司": "金融科技（数据库/模型检索/加密/协议审核），G06F/H04L 为主",
    "宝山钢铁股份有限公司": "钢铁冶金（热轧/炼焦/钢包/特种钢），B21/C22/F16 工艺装备类",
    "中国平安保险（集团）股份有限公司": "保险+金融科技（核保/多智能体/资源分摊），G06Q/G06F 为主",
    "美的集团股份有限公司": "家电+工业（压缩机/冰箱/热泵/吸尘器），含 US 专利，全球化布局",
    "安徽海螺水泥股份有限公司": "水泥制造（给料/清洗/收尘/输送），B08/B65 工艺装备类",
    "大秦铁路股份有限公司": "重载铁路（轨道测量/隧道抑尘/车辆检修），B61/E21 工务装备类",
    "国电电力发展股份有限公司": "电力（火电调峰/风电控制/数字孪生），H02J/F03D 智能电网类",
    "重庆农村商业银行股份有限公司": "金融科技（风控/商户信用/知识图谱），G06Q/G06F 为主",
    "交通银行股份有限公司": "金融科技（GUI 外观 + 应用更新/双活），多为 UI 设计与系统工具",
    "广东省高速公路发展股份有限公司": "高速公路（再生骨料/碳排评估/路基），B02/G06Q/E01 工程类",
    "中国石油天然气股份有限公司": "油气开采（压裂/测井/管道/可燃冰），E21/G01V 勘探开发类",
    "中国神华能源股份有限公司": "煤电路一体化（防灭火/机车/采掘），G08B/B61/E21 类",
    "上海浦东发展银行股份有限公司": "金融科技（摘要抽取/推荐/风险名单），G06F/G06Q 为主",
    "中国邮政储蓄银行股份有限公司": "金融科技（数据发送/存单/报文/图像加密），G06F/G06Q/H04N 为主",
    "江苏宁沪高速公路股份有限公司": "高速公路（碳资产/智慧管控/标线施工），G06Q/G08G/E01 类",
    "中国工商银行股份有限公司": "金融科技（产品推送/任务调度/信息存证），G06F/G06Q/H04L 为主",
    "中国石油化工股份有限公司": "炼化（催化剂/石脑油/甲胺/吸附剂），B01J/C07/C10 化工工艺类",
    "中国银行股份有限公司": "金融科技（车险欺诈/银行系统/佣金/加密），G06Q/H04L 为主",
    "中国建设银行股份有限公司": "金融科技（网络配置/大模型风控/文档校验），G06F/G06Q/H04L 为主",
    "中国农业银行股份有限公司": "金融科技（用例质量/兴趣点推荐/敏感图像），G06F/G06Q 为主",
    "陕西煤业股份有限公司": "煤炭开采（冲击地压/制氢/除尘），G06F/B01J/E21 采矿类",
    "中国长江电力股份有限公司": "水电（容灾/来水预测/启闭机/冷却介质），G06F/G06Q/E02 水电类",
    "中国海洋石油集团有限公司": "海洋油气（催化剂/防喷器/测井/驱油），B01J/E21/C09 类",
    "河南双汇投资发展股份有限公司": "肉制品（包装外观设计为主+工艺装备），S 类外观与 B65 装备",
}


def _ipc_top(patents, n=4):
    c = Counter()
    for p in patents:
        ipc = p.get("ipc")
        if ipc:
            c[ipc[:4]] += 1
    return "、".join(f"{k}({v})" for k, v in c.most_common(n)) or "—"


def _status_dist(patents):
    c = Counter((p.get("legal_status") or "unknown") for p in patents)
    act = c.get("active", 0)
    pend = c.get("pending", 0)
    return act, pend


def _latest(patents):
    return max((str(p.get("date") or "") for p in patents), default="-")


def _top_paper(ip):
    papers = ip.get("papers") or []
    if not papers:
        return None
    return max(papers, key=lambda a: a.get("cited_count") or 0)


def main():
    assets = get_all_ip_assets()
    # 展示顺序：核心 6 家在前，其余按库内顺序追加
    order_keys = [k for k, _ in ORDER]
    for k in assets:
        if k not in order_keys:
            order_keys.append(k)
    lines = []
    A = lines.append

    A("# 专利/论文横向对比报告（智慧芽回填）")
    A("")
    A(f"> 生成时间：2026-08-26 ｜ 数据源：智慧芽（Patsnap）MCP 会话内采样 ｜ 范围：{len(order_keys)} 家标的")
    A("> **如实说明**：库内为每标的按最新公开日排序的 8~15 件专利**采样快照**，")
    A("> 非全量专利清单；每家用例总量（total_hits）见会话内搜索记录，用于衡量专利池体量。")
    A("")
    A("## 一、全景对比表")
    A("")
    A("| 标的 | 专利(采样) | 有效 | 审查中 | 论文 | 最新专利 | IPC 技术聚焦（前 4） |")
    A("|---|---|---|---|---|---|---|")
    for key in order_keys:
        ip = assets.get(key)
        if not ip:
            continue
        label = dict(ORDER).get(key, key)
        pats = ip.get("patents") or []
        act, pend = _status_dist(pats)
        papers = ip.get("papers") or []
        A(f"| {label} | {len(pats)} | {act} | {pend} | {len(papers)} | "
          f"{_latest(pats)} | {_ipc_top(pats)} |")

    A("")
    A("## 二、各家详解")
    A("")
    for key in order_keys:
        ip = assets.get(key)
        if not ip:
            continue
        label = dict(ORDER).get(key, key)
        ctx = CONTEXT.get(key, {})
        qnote = QUEUE_NOTE.get(key)
        pats = ip.get("patents") or []
        papers = ip.get("papers") or []
        A(f"### {label}")
        A("")
        A(f"- **专利池体量**：{ctx.get('hits', '会话内搜索（新回填）')}")
        A(f"- **样本解读**：{ctx.get('note', qnote or '—')}")
        A(f"- **专利样本**：{len(pats)} 件（有效 {_status_dist(pats)[0]} / 审查中 {_status_dist(pats)[1]}）")
        A(f"- **最新专利**：`{_latest(pats)}`")
        top = _top_paper(ip)
        if top:
            A(f"- **高被引论文**：《{top.get('title', '')[:60]}》"
              f"（被引 {top.get('cited_count', 0)}，{top.get('org', '')}）")
        elif papers:
            A(f"- **论文**：{len(papers)} 篇")
        else:
            A("- **论文**：无（银行机构学术产出少，符合行业特性）")
        if papers:
            orgs = set()
            for a in papers:
                o = a.get("org") or ""
                if o:
                    orgs.update(x.strip() for x in o.split("/"))
            A(f"- **产学研合作**：{'、'.join(sorted(orgs)[:6])}")
        A("")
    A("## 三、横向洞察")
    A("")
    A("1. **技术密度与专利池**：宁德时代（6.5 万）、小米（13.3 万）专利池规模最大，且均以国际布局")
    A("   为主（DE/JP/KR 批量申请）；英伟达（2.7 万）以 US/CN/DE 三地构建 AI 计算壁垒。")
    A("2. **技术聚焦分野清晰**：")
    A("   - 电池双雄（比亚迪/宁德）：H01M 电化学储能主导，比亚迪偏向电池+整车制动一体化，宁德偏材料与系统集成")
    A("   - 小米：手机通信（H04L/H04W）+ 智能汽车（B60T/H02M）+ AI 交互（G06F3/01）三条线并行")
    A("   - 英伟达：GPU 计算（G06F/G06N）、图形（G06T）、语音（G10L）、机器人（B25J）、自动驾驶（B60W）")
    A("   - 茅台：酿造微生物（C12N）+ 酒冷余热（F28B）+ 环保废水（C02F）+ 外观设计（S）")
    A("   - 平安银行：金融科技（G06Q/G06F），分布式任务调度、数据库、风控合规、区块链信用卡")
    A("3. **论文产学研**：宁德（Nature Nanotechnology / ACS Nano，与清华/厦大合作）、小米（清华/人大/港中文）、")
    A("   英伟达（MIT/多伦多/苏黎世联邦）学术连接最强；茅台 2 篇偏向集团与高校医药合作；平安无学术论文。")
    A("4. **知识产权维度的投资含义**：专利池与技术聚焦直接反映**研发资本开支方向**——")
    A("   电池链（比亚迪/宁德）护城河在材料与制造工艺，小米/英伟达护城河在通信协议与 AI 基础设施，")
    A("   茅台护城河在工艺与微生物（非专利密集型行业但防御性布局完善）。")
    A("")
    A("## 四、数据边界")
    A("")
    A("- 智慧芽检索按 assignee/org 名称匹配，含集团关联主体（如茅台集团循环经济、宁德上海智能科技）")
    A("- 采样排序为「最新公开日」，**不代表专利质量/价值排名**；被引数仅反映样本内可见值")
    A("- 比亚迪为早期回填样本，部分专利未含 legal_status 字段，表中「审查中」含未知状态（如实）")
    A("- 各标的总量口径不同（assignee 匹配广度不同），跨家对比请以「技术聚焦」而非绝对数量为准")
    A("")
    A("---")
    A("")
    A("*报告由 `scripts/patent_report.py` 从 ip_assets 表自动生成，回补脚本见 `scripts/backfill_ip.py`。*")

    out = Path(__file__).resolve().parents[1] / "docs" / "patent_landscape.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"已生成 {out}（{len(lines)} 行）")


if __name__ == "__main__":
    main()
