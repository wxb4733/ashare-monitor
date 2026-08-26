"""补拉研发型企业论文（智慧芽 paper）→ 合并进 ip_assets。

批次 2026-08-26：宇通/华域/海尔/美的/海螺/中石油/陕煤 7 家。
如实标注：格力 0 篇、双汇 0 篇、中海油 0 篇、长江电力 0 篇（学术产出少或
org 匹配为空）；宝钢检索命中 6 篇但均为「上海第二医科大学附属宝钢医院」
医学论文（医疗机构同名，与宝钢股份无关），不入库。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ashare_monitor.import_data import import_ip_assets  # noqa: E402


def _pd(v: int | str | None) -> str:
    """YYYYMMDD int → YYYY-MM-DD；空则 ''。"""
    if not v:
        return ""
    s = str(v)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else s


def _papers(docs: list[dict]) -> list[dict]:
    """MCP 返回 docs → 库内 papers 字段。"""
    out = []
    for d in docs:
        org = (d.get("org_names") or [""])[0]
        authors = (d.get("authors") or [])[:6]
        out.append({
            "title": (d.get("title") or "").strip(),
            "authors": authors,
            "org": org,
            "date": _pd(d.get("publication_date")),
            "journal": d.get("journal_name") or "",
            "cited_count": d.get("cited_count") or 0,
        })
    return out


# (公司键, 论文 docs)
DATA: list[tuple[str, list[dict]]] = [
    ("宇通客车股份有限公司", [
        {"title": "Identification of Suspension Kingpin Alignment Parameters Based on Screw Axis Theorem and Differential Calculation Model", "authors": ["Ding, Jinquan", "Hou, Junjian", "Zhao, Dengfeng", "Guo, Yaohua"], "org_names": ["Yutong Bus Co., Ltd."], "publication_date": 20250506, "journal_name": "Society of Automotive Engineers Technical Paper Series", "cited_count": 0},
        {"title": "Bi-Att3DDet: Attention-Based Bi-Directional Fusion for Multi-Modal 3D Object Detection", "authors": ["Gao, Xu", "Zhao, Yaqian", "Wang, Yanan", "Shang, Jiandong", "Zhang, Chunmin", "Wu, Gang"], "org_names": ["Zhengzhou University", "Yutong Bus Co., Ltd."], "publication_date": 20250123, "journal_name": "SENSORS", "cited_count": 4},
        {"title": "Starting driving style recognition of electric city bus based on deep learning and CAN data", "authors": ["Zhao, Dengfeng", "Fu, Zhijun", "Liu, Chaohui", "Hou, Junjian", "Dong, Shesen", "Zhong, Yudong"], "org_names": ["Yutong Bus Co., Ltd."], "publication_date": 20241210, "journal_name": "Transport", "cited_count": 0},
        {"title": "A Green Wave Ecological Global Speed Planning under the Framework of Vehicle-Road-Cloud Integration", "authors": ["Li, Zhe", "Ji, Xiaolei", "Yuan, Shuai", "Fang, Zengli", "Liu, Zhennan", "Gao, Jianping"], "org_names": ["Yutong Bus Co., Ltd."], "publication_date": 20240904, "journal_name": "Electronics", "cited_count": 2},
        {"title": "Adaptive Anti-Surge Control Strategy for PEM Fuel Cell Vehicle With Online Surge Detection", "authors": ["Liu, Zhaoming", "Chang, Guofeng", "Jiang, Shangfeng", "Wei, Xuezhe", "Yuan, Hao", "Xie, Jiaping"], "org_names": ["Tongji University", "Yutong Bus Co., Ltd."], "publication_date": 20240301, "journal_name": "IEEE Transactions on Transportation Electrification", "cited_count": 18},
        {"title": "Experimental and numerical study of the temperature evolution in hydrogen cylinder under fast-refueling process", "authors": ["Mengxiao Li", "Qiao Yang", "Caizhi Zhang", "Song Huang", "Mingjun Zhang", "Guo Zhang"], "org_names": ["Yutong Bus Co., Ltd."], "publication_date": 20230901, "journal_name": "INTERNATIONAL JOURNAL OF HEAT AND MASS TRANSFER", "cited_count": 44},
        {"title": "A novel dual power-driven electric power steering system for electric commercial vehicles", "authors": ["Fu, Zhijun", "Lu, Yan", "Zhao, Dengfeng", "Yuan, Peixin", "Guo, Yaohua"], "org_names": ["Yutong Bus Co., Ltd."], "publication_date": 20230901, "journal_name": "Advances in Mechanical Engineering", "cited_count": 18},
        {"title": "Research Progress on Data-Driven Methods for Battery States Estimation of Electric Buses", "authors": ["Zhao, Dengfeng", "Li, Haiyang", "Zhou, Fang", "Zhong, Yudong", "Zhang, Guosheng", "Liu, Zhaohui"], "org_names": ["Yutong Bus Co., Ltd."], "publication_date": 20230602, "journal_name": "World Electric Vehicle Journal", "cited_count": 21},
    ]),
    ("华域汽车系统股份有限公司", [
        {"title": "Automatic Azimuth Alignment for Automotive Radar", "authors": ["Guo, Jianying", "Sun, Shuangsuo", "Li, Kun"], "org_names": ["Huayu Automotive Systems Co., Ltd."], "publication_date": 20180807, "journal_name": "Society of Automotive Engineers Technical Paper Series", "cited_count": 8},
    ]),
    ("海尔智家股份有限公司", [
        {"title": "Numerical study of flow boiling in inclined large length-diameter microchannels", "authors": ["He, Xinyu", "Wang, Dechang", "Song, Qinglu", "Liu, Zhanjie", "Zhou, Sai"], "org_names": ["Qingdao Haier Biomedical Co., Ltd."], "publication_date": 20260101, "journal_name": "Thermal Science", "cited_count": 1},
        {"title": "Versatile filter membrane for effective sampling and real-time quantitative detection of airborne pathogens", "authors": ["Yan, Saisai", "Liu, Qing", "Xing, Kunyue", "Liu, Zhanjie", "Guo, Han", "Jiang, Wenhao"], "org_names": ["Qingdao Haier Biomedical Co., Ltd."], "publication_date": 20240801, "journal_name": "JOURNAL OF HAZARDOUS MATERIALS", "cited_count": 14},
        {"title": "PERFORMANCE ENHANCEMENT OF BRASS EDM ELECTRODES WITH CRYOGENIC TREATMENT WHILE MACHINING THE COLD WORK STEEL AISI D2", "authors": ["ÇAKIR, FATIH HAYATI", "CERITBINMEZ, FERHAT"], "org_names": ["Haier Group Corp."], "publication_date": 20240517, "journal_name": "SURFACE REVIEW AND LETTERS", "cited_count": 4},
        {"title": "WITHDRAWN: Intraarticular Injection of Different Doses of Mesenchymal Stem Cell Derived Exosomes Reduces ATF-3 Expression in the Dorsal Root Ganglion in Monoiodoacetate-Induced Rats of Osteoarthritis", "authors": ["Zhou, Wenwen", "Wang, Lin", "Cao, Qilong", "LI, Xinhe", "Hu, Yue", "Li, Juan"], "org_names": ["Haier Group Corp."], "publication_date": 20210524, "journal_name": "", "cited_count": 1},
        {"title": "Adaptive fuzzy discrete-time fault-tolerant control for permanent magnet synchronous motors based on dynamic surface technology", "authors": ["Guobin Zhang", "Jiapeng Liu", "Zhanjie Liu", "Jinpeng Yu", "Yumei Ma"], "org_names": ["Qingdao Haier Biomedical Co., Ltd."], "publication_date": 20200901, "journal_name": "NEUROCOMPUTING", "cited_count": 15},
        {"title": "Paradoxes and Paradoxical Leader Behaviors: Evidence from the 35-Year Corporate Development of Haier", "authors": ["Xu, Liguo", "Fu, Ping Ping", "Zheng, Xianjing", "Zhou, Yunjie", "Lin, Boxiang"], "org_names": ["Haier Group Corp."], "publication_date": 20200801, "journal_name": "Academy of Management Proceedings", "cited_count": 1},
        {"title": "Finite-time dynamic surface control for induction motors with input saturation in electric vehicle drive systems", "authors": ["Huijuan Luo", "Jinpeng Yu", "Chong Lin", "Zhanjie Liu", "Lin Zhao", "Yumei Ma"], "org_names": ["Qingdao Haier Biomedical Co., Ltd."], "publication_date": 20191201, "journal_name": "NEUROCOMPUTING", "cited_count": 24},
        {"title": "Combinatorial Research of Molecular Technologies and Surface Nanostructures Applied to the Development of Antifouling Coatings", "authors": ["Yin, Bing", "Liu, Chaohong"], "org_names": ["Haier Group Corp."], "publication_date": 20190601, "journal_name": "JOURNAL OF NANOSCIENCE AND NANOTECHNOLOGY", "cited_count": 8},
    ]),
    ("美的集团股份有限公司", [
        {"title": "Vibration response-based real-time monitoring system for RV reducer bearings", "authors": ["Feng, Wujun", "Huang, Yukun", "Xue, Linlin", "Luo, Huageng", "Zhang, Xinyue", "Wang, Gang"], "org_names": ["Midea Group Co. Ltd."], "publication_date": 20251230, "journal_name": "STRUCTURAL HEALTH MONITORING-AN INTERNATIONAL JOURNAL", "cited_count": 1},
        {"title": "MEAN-RIR: Multi-Modal Environment-Aware Network for Robust Room Impulse Response Estimation", "authors": ["Chen, Jiajian", "Chen, Jiakang", "Chen, Hang", "Wang, Qing", "Gao, Yu", "Du, Jun"], "org_names": ["Midea Group Co. Ltd."], "publication_date": 20251206, "journal_name": "ArXiv", "cited_count": 2},
        {"title": "PhysEmbedFormer: A Physics-Guided Interpretable Architecture for Medium-Term Forecasting of PV Power", "authors": ["Yu, Yue", "Loskot, Pavel", "Gao, Yu"], "org_names": ["Midea Group Co. Ltd."], "publication_date": 20251031, "journal_name": "", "cited_count": 0},
        {"title": "LEGO: A Lightweight and Efficient Multiple-Attribute Unlearning Framework for Recommender Systems", "authors": ["Yu, Fengyuan", "Li, Yuyuan", "Feng, Xiaohua", "Fang, Junjie", "Wang, Tao", "Chen, Chaochao"], "org_names": ["Midea Group Co. Ltd."], "publication_date": 20251027, "journal_name": "Proceedings of the 33rd ACM International Conference on Multimedia", "cited_count": 3},
        {"title": "DuAda: Adaptive Targeted Model Poisoning Attack Framework via Dummy User Simulation on Federated Recommendation", "authors": ["Su, Jiajie", "Chen, Chaochao", "Wang, Yihao", "Liu, Weiming", "Li, Yuyuan", "Wang, Tao"], "org_names": ["Midea Group Co. Ltd."], "publication_date": 20250910, "journal_name": "ACM TRANSACTIONS ON INFORMATION SYSTEMS", "cited_count": 2},
        {"title": "CoA-VLA: Improving Vision-Language-Action Models via Visual-Textual Chain-of-Affordance", "authors": ["Jinming Li", "Yichen Zhu", "Zhibin Tang", "Junjie Wen", "Minjie Zhu", "Xiaoyu Liu"], "org_names": ["Midea Group Co. Ltd."], "publication_date": 20250801, "journal_name": "ArXiv", "cited_count": 0},
        {"title": "Performance improvement of centrifugal compressors by suppressing backward heat transfer", "authors": ["Tengda Zou", "Tongtong Zhang", "Xiaowen Hu"], "org_names": ["Midea Group Co. Ltd."], "publication_date": 20250801, "journal_name": "International Journal of Refrigeration", "cited_count": 0},
        {"title": "Numerical and Experimental Study on Valve Impact Induced Noise and Vibration for Rotary Compressors", "authors": ["He, Dazhuang", "Tan, Shupeng SHUPENG", "Cui, Yidan", "Lee, Joohyun", "Liu, Yangfan", "Ziviani, Davide"], "org_names": ["Midea Group Co. Ltd."], "publication_date": 20250725, "journal_name": "INTER-NOISE and NOISE-CON Congress and Conference Proceedings", "cited_count": 0},
    ]),
    ("安徽海螺水泥股份有限公司", [
        {"title": "An Improved Carbon Dioxide Monitoring Method Related to China's Carbon Emissions Trading System in Cement Plants", "authors": ["Wu, Tiejun", "Fan, Jingwei", "Zhou, Li", "Qian, Jueying", "Li, Zhuotong", "Bai, Wenhao"], "org_names": ["Anhui Conch Cement Co., Ltd."], "publication_date": 20260205, "journal_name": "Processes", "cited_count": 0},
        {"title": "Accelerated carbonation of MSWI fly ash as a supplementary precursor in alkali-activated materials", "authors": ["Yubo Sun", "Yaxin Tao", "Zhenming Li", "Wenjun Lu", "Zhiyuan Liu", "Shengtian Zhai"], "org_names": ["Anhui Conch Cement Co., Ltd."], "publication_date": 20250401, "journal_name": "Developments in the Built Environment", "cited_count": 2},
    ]),
    ("中国石油天然气股份有限公司", [
        {"title": "Thermo-Mechanical Controls on Permeability in Deep Fractured-Porous Carbonates During Underground Gas Storage", "authors": ["Zhai, Zhen", "Gan, Quan", "Wang, Yan", "Huang, Saipeng", "Zhao, Yuchao", "Li, Limin"], "org_names": ["PetroChina Company Limited"], "publication_date": 20260122, "journal_name": "Energies", "cited_count": 1},
        {"title": "A Combined Glutaraldehyde and Denitrifying Bacteria Strategy for Enhanced Control of SRB-Induced Corrosion in Shale Gas Infrastructure", "authors": ["Guo, Yu", "Wen, Chongrong", "Duan, Ming", "Lan, Guihong"], "org_names": ["PetroChina Company Limited"], "publication_date": 20260117, "journal_name": "Processes", "cited_count": 0},
        {"title": "Fabrication of Microphase-Separated Tröger's Base Polymer Membranes for Oxygen Enrichment", "authors": ["Yang, Chaoyue", "Zhou, Li", "Zhang, Qian", "Huang, Ya", "Zhang, Peixiao", "Xue, Jingwen"], "org_names": ["PetroChina Company Limited"], "publication_date": 20251230, "journal_name": "Membranes", "cited_count": 0},
        {"title": "Review of Cement-Based Plugging Systems for Severe Lost Circulation in Deep and Ultra-Deep Formations", "authors": ["Ma, Biao", "Zheng, Kun", "Zhang, Chengjin", "Pu, Lei", "Feng, Bin", "Shi, Qing"], "org_names": ["PetroChina Company Limited"], "publication_date": 20251225, "journal_name": "Processes", "cited_count": 4},
        {"title": "Source-Reservoir Structure of Member 2 of Xujiahe Formation and Its Control on Differential Enrichment of Tight Sandstone Gas in the Anyue Area, Sichuan Basin", "authors": ["Long, Hui", "Gao, Tian", "Chen, Dongxia", "Lei, Wenzhi", "Sun, Xuezhen", "Yang, Hanxuan"], "org_names": ["PetroChina Company Limited"], "publication_date": 20251219, "journal_name": "Energies", "cited_count": 1},
        {"title": "Study on the Evolution Law of Four-Dimensional In Situ Stress During Hydraulic Fracturing of Deep Shale Gas Reservoir", "authors": ["Cui, Shuai", "Wu, Jianfa", "Zeng, Bo", "Huang, Haoyong", "Wang, Shouyi", "Liu, Houbin"], "org_names": ["PetroChina Company Limited"], "publication_date": 20251121, "journal_name": "Processes", "cited_count": 0},
        {"title": "Timing and Effect of the Hidden Thrust Fault on the Tight Reservoir in the Southeastern Sichuan Basin", "authors": ["Long, Hui", "Jiang, Tongwen", "Wang, Jiamu", "Tang, Hao", "Qiu, Chen", "Liu, Tian"], "org_names": ["PetroChina Company Limited"], "publication_date": 20251118, "journal_name": "Minerals", "cited_count": 2},
        {"title": "New Insights on the Geometry of Simultaneous Multiple Fracture Propagation in Laminated Shale Reservoirs Considering the Effects of Bedding Planes and Stress Interference", "authors": ["He, Rui", "Sang, Yu", "Li, Li", "Chen, Weihua", "Zeng, Ji", "Wang, Tao"], "org_names": ["PetroChina Company Limited"], "publication_date": 20251103, "journal_name": "ADIPEC", "cited_count": 0},
    ]),
    ("陕西煤业股份有限公司", [
        {"title": "Characteristics of the Main Controlling Factors and Formation-Evolution Process of Karst Collapse Columns in the Hancheng Mining Area, Northern China", "authors": ["Chen, Yingtao", "Yang, Xufeng", "Zhang, Huan", "Dai, Gelian", "Luo, Shoutao", "Yu, Wenxin"], "org_names": ["Shaanxi Coal & Chemical Industry Group Co., Ltd."], "publication_date": 20251030, "journal_name": "Water", "cited_count": 1},
        {"title": "Disaster treatment and multisource monitoring of rockbursts in isolated island coal face under hard roof conditions", "authors": ["Yun, Mengchen", "Ren, Jianxi", "Zhang, Liang", "Guo, Fengjing", "Chen, Xu"], "org_names": ["Shaanxi Coal & Chemical Industry Group Co., Ltd."], "publication_date": 20250821, "journal_name": "Scientific Reports", "cited_count": 5},
        {"title": "Evaluation of Water Richness in Sandstone Aquifers Based on the CRITIC-TOPSIS Method: A Case Study of the Guojiawan Coal Mine in Fugu Mining Area, Shaanxi Province, China", "authors": ["Niu, Chao", "Jia, Xiangqun", "Xiao, Lele", "Dong, Lei", "Qiao, Hui", "Huang, Fujing"], "org_names": ["Shaanxi Coal & Chemical Industry Group Co., Ltd."], "publication_date": 20250509, "journal_name": "Water", "cited_count": 2},
        {"title": "Physical Simulation Experiment on the Rock Breaking Efficiency of Pulse Type Controllable Shock Wave", "authors": ["Wang, Shubin", "Zhang, Shuo", "Ma, Liang", "Zhao, Youzhi", "Gao, Liang", "Cao, Yuxiang"], "org_names": ["Shaanxi Coal & Chemical Industry Group Co., Ltd."], "publication_date": 20241217, "journal_name": "ACS Omega", "cited_count": 1},
        {"title": "Distinct bacterial signature in the raw coal with different heating value", "authors": ["Zou, Haijiang", "Tian, Miaomiao", "Xu, Jianmin", "Li, Guowei", "Chen, Hui", "Yang, Junjun"], "org_names": ["Shaanxi Coal & Chemical Industry Group Co., Ltd."], "publication_date": 20240905, "journal_name": "Frontiers in Microbiology", "cited_count": 3},
        {"title": "Hybrid Integration of Bagging and Decision Tree Algorithms for Landslide Susceptibility Mapping", "authors": ["Zhang, Qi", "Ning, Zixin", "Ding, Xiaohu", "Wu, Junfeng", "Wang, Zhao", "Tsangaratos, Paraskevas"], "org_names": ["Shaanxi Coal & Chemical Industry Group Co., Ltd."], "publication_date": 20240223, "journal_name": "Water", "cited_count": 13},
        {"title": "A Case Study on the CO2 Sequestration in Shenhua Block Reservoir: The Impacts of Injection Rates and Modes", "authors": ["Tang, Ligen", "Ding, Guosheng", "Song, Shijie", "Wang, Huimin", "Xie, Wuqiang", "Wang, Jiulong"], "org_names": ["Shaanxi Coal & Chemical Industry Group Co., Ltd."], "publication_date": 20231225, "journal_name": "Energies", "cited_count": 2},
        {"title": "Effect of Confining Pressure on CO2-Brine Relative Permeability Characteristics of Sandstone in Ordos Basin", "authors": ["Tang, Ligen", "Ding, Guosheng", "Song, Shijie", "Wang, Huimin", "Xie, Wuqiang", "Zhou, Yiyang"], "org_names": ["Shaanxi Coal & Chemical Industry Group Co., Ltd."], "publication_date": 20231209, "journal_name": "Water", "cited_count": 10},
    ]),
]


def main() -> int:
    total = 0
    for company, docs in DATA:
        papers = _papers(docs)
        ok = import_ip_assets(company, patents=None, papers=papers)
        print(f"  {'✅' if ok else '❌'} {company}: +{len(papers)} 篇")
        total += len(papers)
    print(f"完成：7 家共 +{total} 篇论文")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
