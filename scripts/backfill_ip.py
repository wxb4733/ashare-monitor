"""一次性回填：智慧芽专利/论文（5 家：茅台/平安/宁德/小米/英伟达）。

MCP 会话内拉取 → 本脚本落库（import_ip_assets 合并去重）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ashare_monitor.import_data import import_ip_assets

# (company_key, patents, papers)
DATA = [
    # ── 贵州茅台 ────────────────────────────────
    ("贵州茅台酒股份有限公司", [
        {"pn": "CN122612431A", "title": "土壤孔隙的水分量化方法、装置、电子设备及存储介质", "date": "2026-08-21", "legal_status": "pending", "ipc": "G01N15/08", "assignees": ["贵州茅台酒股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122581387A", "title": "酱香型酒糟发酵功能性饲料在肠黏膜炎环境下改善雌性动物子宫免疫稳态中的应用", "date": "2026-08-18", "legal_status": "pending", "ipc": "A23K50/00", "assignees": ["贵州茅台酒厂(集团)循环经济产业投资开发有限公司"], "jurisdiction": "CN"},
        {"pn": "CN310153600S", "title": "酒盒(汉圣酒·圣宴)", "date": "2026-08-18", "legal_status": "active", "ipc": None, "assignees": ["贵州茅台镇汉圣酒业有限公司"], "jurisdiction": "CN"},
        {"pn": "CN310146515S", "title": "酒盒(汉圣酒珍藏)", "date": "2026-08-14", "legal_status": "active", "ipc": None, "assignees": ["贵州茅台镇汉圣酒业有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122578285A", "title": "基于多级网络安全指标体系进行网络安全评估的方法及系统", "date": "2026-08-14", "legal_status": "pending", "ipc": "H04L9/40", "assignees": ["中国贵州茅台酒厂(集团)有限责任公司"], "jurisdiction": "CN"},
        {"pn": "CN224622037U", "title": "冷却器的减震座", "date": "2026-08-11", "legal_status": "active", "ipc": "F16F15/067", "assignees": ["贵州茅台酒股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN310134542S", "title": "酒盒", "date": "2026-08-07", "legal_status": "active", "ipc": None, "assignees": ["贵州茅台酱香酒营销有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122529135A", "title": "摊晾面积预测方法、装置、电子设备及存储介质", "date": "2026-08-07", "legal_status": "pending", "ipc": "G06Q10/04", "assignees": ["贵州茅台酒股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122521466A", "title": "一种粟酒裂殖酵母的培养基及其应用", "date": "2026-08-07", "legal_status": "pending", "ipc": "C12N1/16", "assignees": ["贵州茅台酒股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122523871A", "title": "酒冷余热的利用方法和系统", "date": "2026-08-07", "legal_status": "pending", "ipc": "F28B1/02", "assignees": ["贵州茅台酒股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN310129423S", "title": "酒瓶（umeet蓝莓蒸馏酒-靛岚）", "date": "2026-08-04", "legal_status": "active", "ipc": None, "assignees": ["贵州茅台(集团)生态农业产业发展有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122487308A", "title": "一种生物传感器及基于该生物传感器的库德里阿兹威毕赤酵母的荧光-磷光双模式检测方法", "date": "2026-07-31", "legal_status": "pending", "ipc": "G01N21/64", "assignees": ["贵州茅台酒股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122464503A", "title": "一种去除废水中亚磷酸盐的电混凝方法及其应用和系统", "date": "2026-07-28", "legal_status": "pending", "ipc": "C02F1/463", "assignees": ["贵州茅台酒股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN224563516U", "title": "一种玻璃瓶加工用上料装置", "date": "2026-07-28", "legal_status": "active", "ipc": "B65G47/14", "assignees": ["贵州茅台酒厂(集团)贵定晶琪玻璃制品有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122468703A", "title": "一种吡嗪类化合物的快速检测方法", "date": "2026-07-28", "legal_status": "pending", "ipc": "G01N21/78", "assignees": ["贵州茅台酒股份有限公司"], "jurisdiction": "CN"},
    ], [
        {"title": "天然活性组分与药效研究（中国药科大学×茅台合作）", "authors": ["林琳", "齐晓冬", "李永素", "杨玉波", "杨鸣华", "陈毅", "孔令义", "王莉"], "org": "中国药科大学 / 贵州茅台酒股份有限公司", "date": "2023-08-25", "journal": "Journal of China Pharmaceutical University", "doi": "10.11665/j.issn.1000-5048.2023040402", "cited_count": 0},
        {"title": "贵州茅台医院相关药理研究（天然产物化学重点实验室等）", "authors": ["郭静", "张启云", "靳翔", "薛焕焕", "路青瑜", "郭丽", "孙黔云", "张立伟"], "org": "贵州省中国科学院天然产物化学重点实验室 / 贵州医科大学 / 贵州茅台医院", "date": "2023-03-20", "journal": "Chinese Pharmacological Bulletin", "doi": "10.12360/cpb202204070", "cited_count": 0},
    ]),
    # ── 平安银行 ────────────────────────────────
    ("平安银行股份有限公司", [
        {"pn": "CN115934335B", "title": "任务处理方法以及相关设备", "date": "2026-08-21", "legal_status": "active", "ipc": "G06F9/50", "assignees": ["平安银行股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN115185988B", "title": "比对方法和比对设备", "date": "2026-08-21", "legal_status": "active", "ipc": "G06F16/2455", "assignees": ["平安银行股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN115883731B", "title": "外呼方法、装置、存储介质及计算机设备", "date": "2026-08-21", "legal_status": "active", "ipc": "H04M3/51", "assignees": ["平安银行股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN115809143B", "title": "网关交易方法及其系统、计算机设备", "date": "2026-08-18", "legal_status": "active", "ipc": "G06F9/50", "assignees": ["平安银行股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN115576897B", "title": "商机档案的创建方法、装置、计算机设备及存储介质", "date": "2026-08-18", "legal_status": "active", "ipc": "G06F16/11", "assignees": ["平安银行股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN116127478B", "title": "日志的脱敏方法、装置、电子设备和存储介质", "date": "2026-08-18", "legal_status": "active", "ipc": "G06F21/60", "assignees": ["平安银行股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN116108090B", "title": "在应用层进行数据库读写分离的方法、系统及设备", "date": "2026-08-14", "legal_status": "active", "ipc": "G06F16/25", "assignees": ["平安银行股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN119089009B", "title": "数据库敏感信息识别方法、异常状态处理方法、相关装置", "date": "2026-08-11", "legal_status": "active", "ipc": "G06F16/903", "assignees": ["平安银行股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN117033413B", "title": "一种复杂SQL语句的可视化方法、装置、系统及介质", "date": "2026-08-07", "legal_status": "active", "ipc": "G06F16/242", "assignees": ["平安银行股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN115509774B", "title": "基于不同应用程序的内容分享方法及其相关设备", "date": "2026-08-04", "legal_status": "active", "ipc": "G06F9/54", "assignees": ["平安银行股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN115630206B", "title": "欢迎语内容的匹配方法、装置和电子设备", "date": "2026-07-31", "legal_status": "active", "ipc": "G06F16/9035", "assignees": ["平安银行股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN117114880B", "title": "信用卡交易系统及方法、设备及存储介质", "date": "2026-07-31", "legal_status": "active", "ipc": "G06Q40/04", "assignees": ["平安银行股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN117217169B", "title": "一种银行流水号生成方法、系统、设备及存储介质", "date": "2026-07-31", "legal_status": "active", "ipc": "G06F40/126", "assignees": ["平安银行股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN117151843B", "title": "银行代销业务的数据处理方法、装置、电子设备及介质", "date": "2026-07-31", "legal_status": "active", "ipc": "G06Q40/02", "assignees": ["平安银行股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN117079022B", "title": "金融用户画像预测方法、装置、电子设备及存储介质", "date": "2026-07-31", "legal_status": "active", "ipc": "G06V10/764", "assignees": ["平安银行股份有限公司"], "jurisdiction": "CN"},
    ], []),
    # ── 宁德时代 ────────────────────────────────
    ("宁德时代新能源科技股份有限公司", [
        {"pn": "DE212024000499U1", "title": "Battery device and power-consuming device", "date": "2026-08-27", "legal_status": "active", "ipc": "H01M50/569", "assignees": ["Contemporary Amperex Technology Co. Limited"], "jurisdiction": "DE"},
        {"pn": "DE202026103421U1", "title": "Lithium-ion secondary battery, battery device and power-consuming device", "date": "2026-08-27", "legal_status": "active", "ipc": "H01M4/58", "assignees": ["Contemporary Amperex Technology Co. Limited"], "jurisdiction": "DE"},
        {"pn": "DE212026000023U1", "title": "Battery device and power-consuming device", "date": "2026-08-27", "legal_status": "active", "ipc": "H01M50/24", "assignees": ["CONTEMPORARY AMPEREX TECHNOLOGY CO. LIMITED"], "jurisdiction": "DE"},
        {"pn": "DE212026000027U1", "title": "Battery device and power-consuming device", "date": "2026-08-27", "legal_status": "active", "ipc": "H01M10/6556", "assignees": ["Contemporary Amperex Technology Co. Limited"], "jurisdiction": "DE"},
        {"pn": "JP7910248B2", "title": "Positive electrode active material, method for manufacturing the same, positive electrode plate containing the same, battery, and power consumption device", "date": "2026-08-24", "legal_status": "active", "ipc": "H01M4/505", "assignees": ["宁德时代新能源科技股份有限公司"], "jurisdiction": "JP"},
        {"pn": "KR1020260127787A", "title": "(未命名 KR 专利)", "date": "2026-08-24", "legal_status": "pending", "ipc": "F16B21/04", "assignees": ["Contemporary Amperex Technology Co., Ltd."], "jurisdiction": "KR"},
        {"pn": "CN224662402U", "title": "吊装工装", "date": "2026-08-21", "legal_status": "active", "ipc": "B66C1/22", "assignees": ["宁德时代(上海)智能科技有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122619733A", "title": "二次电池、用电装置、负极活性材料的制备方法和二次电池的制备方法", "date": "2026-08-21", "legal_status": "pending", "ipc": "H01M4/36", "assignees": ["宁德时代新能源科技股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN117689600B", "title": "电芯检测方法、装置、设备、可读存储介质及程序产品", "date": "2026-08-21", "legal_status": "active", "ipc": "G06T7/00", "assignees": ["宁德时代新能源科技股份有限公司"], "jurisdiction": "CN"},
        {"pn": "JP2026528406A", "title": "Current collection pipes, thermal management assemblies, batteries, and power consumption equipment", "date": "2026-08-21", "legal_status": "pending", "ipc": "H01M10/6568", "assignees": ["宁德时代新能源科技股份有限公司"], "jurisdiction": "JP"},
        {"pn": "CN116783498B", "title": "电池自放电检测方法、电路和设备", "date": "2026-08-21", "legal_status": "active", "ipc": "G01R31/36", "assignees": ["宁德时代新能源科技股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN224668919U", "title": "电池装置和用电装置", "date": "2026-08-21", "legal_status": "active", "ipc": "H01M50/569", "assignees": ["宁德时代新能源科技股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122619997A", "title": "电池装置及用电装置", "date": "2026-08-21", "legal_status": "pending", "ipc": "H01M10/613", "assignees": ["宁德时代新能源科技股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN224668817U", "title": "电池装置及用电装置", "date": "2026-08-21", "legal_status": "active", "ipc": "H01M50/244", "assignees": ["宁德时代新能源科技股份有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122619996A", "title": "电池装置、储能装置和用电装置", "date": "2026-08-21", "legal_status": "pending", "ipc": "H01M10/613", "assignees": ["宁德时代新能源科技股份有限公司"], "jurisdiction": "CN"},
    ], [
        {"title": "Enhancing image restoration through learning context-rich and detail-accurate features", "authors": ["Gao, Hu", "Lei, Xiaoning", "Dang, Depeng"], "org": "Shanghai Jiao Tong University / Contemporary Amperex Technology", "date": "2026-02-01", "journal": "NEURAL NETWORKS", "doi": "10.1016/j.neunet.2025.108096", "cited_count": 2},
        {"title": "SARD: Segmentation-Aware Anomaly Synthesis via Region-Constrained Diffusion with Discriminative Mask Guidance", "authors": ["Wang, Yanshu", "Xu, Xichen", "Lei, Xiaoning", "Xie, Guoyang"], "org": "SJTU / CATL", "date": "2025-10-31", "journal": "ArXiv", "doi": "10.1109/mind67540.2025.11351901", "cited_count": 1},
        {"title": "Influence of lithium salt anions on the interfacial properties of PEO-based solid-state electrolytes", "authors": ["Wei, Yi-Min", "Qiu, An", "Wang, Jingchao", "Gu, Yu", "Li, Jian-Feng"], "org": "CATL", "date": "2025-08-01", "journal": "ELECTROCHEMISTRY COMMUNICATIONS", "doi": "10.1016/j.elecom.2025.107979", "cited_count": 4},
        {"title": "Pseudocapacitive materials for energy storage: properties, mechanisms, and applications in supercapacitors and batteries", "authors": ["Wei, Yi-Min", "Kumar, Kulurumotlakatla Dasha", "Zhang, Long", "Li, Jian-Feng"], "org": "CATL / Xiamen University", "date": "2025-06-27", "journal": "Frontiers in Chemistry", "doi": "10.3389/fchem.2025.1636683", "cited_count": 82},
        {"title": "Comprehensive MILP Formulation and Solution for Simultaneous Scheduling of Machines and AGVs in a Partitioned Flexible Manufacturing System", "authors": ["Cheng Zhuang", "Jingbo Qu", "Tianyu Wang", "Liyong Lin", "Youyi Bi", "Mian Li"], "org": "SJTU / CATL", "date": "2025-06-13", "journal": "Machines", "doi": "10.3390/machines13060519", "cited_count": 1},
        {"title": "Carbon Footprint and Decarbonization Potential of Battery-Grade Synthetic Graphite", "authors": ["Wang, Fang", "Zhang, Shaojun", "Liu, Min", "Xiong, Yiling", "De Castro Gomez, Daniel", "He, Xin", "Wu, Ye"], "org": "Tsinghua University / CATL", "date": "2025-05-29", "journal": "ACS Sustainable Chemistry & Engineering", "doi": "10.1021/acssuschemeng.5c00921", "cited_count": 10},
        {"title": "Application-driven design of non-aqueous electrolyte solutions through quantification of interfacial reactions in lithium metal batteries", "authors": ["Wang, Hansen", "Yan, Xiaolin", "Zhang, Rupeng", "Sun, Juanjuan", "Feng, Fuxiang", "Xu, Bo", "Ouyang, Chuying"], "org": "CATL / Jiangxi Normal University", "date": "2025-05-28", "journal": "Nature Nanotechnology", "doi": "10.1038/s41565-025-01935-y", "cited_count": 35},
        {"title": "Solid-Solution Phase Transition Induced by Surface Electrochemico–Mechanical Interactions for High-Voltage Sodium-Layered Oxide Cathodes", "authors": ["Liang, Zibin", "Ouyang, Chuying", "Li, Longze", "Cheng, Lixun", "Cheng, Sulan", "Wang, Yuhao", "Xu, Bo", "Wu, Kai"], "org": "CATL / Jiangxi Normal University", "date": "2025-04-22", "journal": "ACS Nano", "doi": "10.1021/acsnano.5c01904", "cited_count": 1},
    ]),
    # ── 小米集团 ────────────────────────────────
    ("小米集团", [
        {"pn": "KRDM246081002S1", "title": "Power adapter", "date": "2026-08-24", "legal_status": "active", "ipc": None, "assignees": ["BEIJING XIAOMI MOBILE SOFTWARE CO., LTD."], "jurisdiction": "KR"},
        {"pn": "JP7910122B2", "title": "Washing methods, washing machines, storage media, and program products", "date": "2026-08-24", "legal_status": "active", "ipc": "D06F33/36", "assignees": ["北京小米移动软件有限公司"], "jurisdiction": "JP"},
        {"pn": "CN122607273A", "title": "一种车辆控制方法、装置、存储介质、电子设备及芯片", "date": "2026-08-21", "legal_status": "pending", "ipc": "B60T7/12", "assignees": ["小米汽车科技有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122621454A", "title": "指示方法、装置、设备及存储介质", "date": "2026-08-21", "legal_status": "pending", "ipc": "H04L27/26", "assignees": ["北京小米移动软件有限公司"], "jurisdiction": "CN"},
        {"pn": "CN310163018S", "title": "电子设备的信息显示图形用户界面的侧边栏", "date": "2026-08-21", "legal_status": "active", "ipc": None, "assignees": ["北京小米移动软件有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122614215A", "title": "显示屏交互方法、装置、设备、介质和程序产品", "date": "2026-08-21", "legal_status": "pending", "ipc": "G06F3/01", "assignees": ["小米汽车科技有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122621824A", "title": "图像传感器、摄像头、电子设备、对焦方法和装置、存储介质及计算机程序产品", "date": "2026-08-21", "legal_status": "pending", "ipc": "H04N25/70", "assignees": ["北京小米移动软件有限公司"], "jurisdiction": "CN"},
        {"pn": "CN224669186U", "title": "电控单元及车辆", "date": "2026-08-21", "legal_status": "active", "ipc": "H01R25/16", "assignees": ["小米汽车科技有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122620937A", "title": "电机控制器、电驱总成及车辆", "date": "2026-08-21", "legal_status": "pending", "ipc": "H02M1/00", "assignees": ["小米汽车科技有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122620195A", "title": "连接器及移动终端", "date": "2026-08-21", "legal_status": "pending", "ipc": "H01R13/502", "assignees": ["北京小米移动软件有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122623391A", "title": "通信方法、第一设备、第二设备、通信装置、系统及介质", "date": "2026-08-21", "legal_status": "pending", "ipc": "H04W28/08", "assignees": ["北京小米移动软件有限公司"], "jurisdiction": "CN"},
        {"pn": "CN117938320B", "title": "块确认方法及装置、存储介质", "date": "2026-08-21", "legal_status": "active", "ipc": "H04L1/1607", "assignees": ["北京小米移动软件有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122623430A", "title": "信息发送、接收方法及装置、网络设备、终端和存储介质", "date": "2026-08-21", "legal_status": "pending", "ipc": "H04W76/10", "assignees": ["北京小米移动软件有限公司"], "jurisdiction": "CN"},
        {"pn": "CN117242867B", "title": "资源处理方法及装置、通信设备及存储介质", "date": "2026-08-21", "legal_status": "active", "ipc": "H04W72/04", "assignees": ["北京小米移动软件有限公司"], "jurisdiction": "CN"},
        {"pn": "CN122623320A", "title": "通信方法、通信设备、存储介质及程序产品", "date": "2026-08-21", "legal_status": "pending", "ipc": "H04L5/00", "assignees": ["北京小米移动软件有限公司"], "jurisdiction": "CN"},
    ], [
        {"title": "Think-Clip-Sample: Slow-Fast Frame Selection for Video Understanding", "authors": ["Tan, Wenhui", "Song, Ruihua", "Li, Jiaze", "Ju, Jianzhong", "Luo, Zhenbo"], "org": "Renmin University of China / Xiaomi, Inc.", "date": "2026-05-03", "journal": "ArXiv", "doi": "10.1109/icassp55912.2026.11465061", "cited_count": 0},
        {"title": "Tight Cache Contention Analysis for WCET Estimation on Multicore Systems", "authors": ["Zhao, Shuai", "Jiang, Jieyu", "Cai, Shenlin", "Liang, Yaowei", "Zhang, Wei", "Zhang, Guoquan", "Gu, Yaoyao", "Xiao, Xiang", "Qin, Wei", "Ouyang, Ouyang", "Chang, Wanli"], "org": "Sun Yat-Sen University / Hunan University / Shandong University / Xiaomi", "date": "2025-12-02", "journal": "ArXiv", "doi": "10.1109/rtss66672.2025.00046", "cited_count": 0},
        {"title": "Hijacking JARVIS: Benchmarking Mobile GUI Agents against Unprivileged Third Parties", "authors": ["Liu, Guohong", "Ye, Jialei", "Liu, Jiacheng", "Li, Yuanchun", "Liu, Wei", "Gao, Pengzhi", "Luan, Jian", "Liu, Yunxin"], "org": "Tsinghua University / UESTC / Peking University / Xiaomi", "date": "2025-11-04", "journal": "ArXiv", "doi": "10.1145/3737902.3768354", "cited_count": 0},
        {"title": "Learning Arbitrary-Scale RAW Image Downscaling with Wavelet-based Recurrent Reconstruction", "authors": ["Ren, Yang", "Jiang, Hai", "Li, Wei", "Yang, Menglong", "Zhang, Heng", "Sheng, Zehua", "Ye, Qingsheng", "Liu, Shuaicheng"], "org": "Sichuan University / Xiaomi / UESTC", "date": "2025-10-27", "journal": "ArXiv", "doi": "10.1145/3746027.3755180", "cited_count": 0},
        {"title": "Controllable Pedestrian Video Editing for Multi-View Driving Scenarios via Motion Sequence", "authors": ["Fu, Danzhen", "Hu, Jiagao", "Zhou, Daiguo", "Wang, Fei", "Wang, Zepeng", "Liao, Wenhua"], "org": "Xiaomi, Inc.", "date": "2025-10-19", "journal": "ArXiv", "doi": "10.1109/iccvw69036.2025.00196", "cited_count": 0},
        {"title": "SliceMamba With Neural Architecture Search for Medical Image Segmentation", "authors": ["Fan, Chao", "Yu, Hongyuan", "Huang, Yan", "Wang, Liang", "Yang, Zhenghan", "Jia, Xibin"], "org": "Beijing University of Technology / Xiaomi / CAS", "date": "2025-10-01", "journal": "IEEE JBHI", "doi": "10.1109/jbhi.2025.3564381", "cited_count": 22},
        {"title": "Q-Frame: Query-aware Frame Selection and Multi-Resolution Adaptation for Video-LLMs", "authors": ["Shaojie Zhang", "Jiahui Yang", "Jianqin Yin", "Zhenbo Luo", "Jian Luan"], "org": "Xiaomi, Inc.", "date": "2025-07-23", "journal": "ArXiv", "cited_count": 0},
        {"title": "k2SSL: A Faster and Better Framework for Self-Supervised Speech Representation Learning", "authors": ["Yang, Yifan", "Zhuo, Jianheng", "Jin, Zengrui", "Ma, Ziyang", "Yang, Xiaoyu", "Yao, Zengwei", "Guo, Liyong", "Kang, Wei", "Kuang, Fangjun", "Lin, Long", "Povey, Daniel", "Chen, Xie"], "org": "SJTU / CUHK / Xiaomi", "date": "2025-06-30", "journal": "ArXiv", "doi": "10.1109/icme59968.2025.11209883", "cited_count": 1},
    ]),
    # ── 英伟达（NVIDIA）────────────────────────
    ("英伟达", [
        {"pn": "CN122614355A", "title": "用于模型定制的服务器端提示调优", "date": "2026-08-21", "legal_status": "pending", "ipc": "G06F8/35", "assignees": ["辉达公司"], "jurisdiction": "CN"},
        {"pn": "CN116736624B", "title": "在光学接近度校正流中对演进掩模形状的并行掩模规则检查", "date": "2026-08-21", "legal_status": "active", "ipc": "G03F1/36", "assignees": ["辉达公司"], "jurisdiction": "CN"},
        {"pn": "CN114556376B", "title": "在并行计算架构上执行加扰和/或解扰", "date": "2026-08-21", "legal_status": "active", "ipc": "G06N3/08", "assignees": ["辉达公司"], "jurisdiction": "CN"},
        {"pn": "CN122614542A", "title": "利用神经网络进行资源分配预测", "date": "2026-08-21", "legal_status": "pending", "ipc": "G06F9/50", "assignees": ["辉达公司"], "jurisdiction": "CN"},
        {"pn": "US20260245309A1", "title": "Mesh topology generation using parallel processing", "date": "2026-08-20", "legal_status": "pending", "ipc": "G06T17/20", "assignees": ["NVIDIA CORPORATION"], "jurisdiction": "US"},
        {"pn": "US20260244592A1", "title": "Dual-edge data bus inversion to reduce IR drop", "date": "2026-08-20", "legal_status": "pending", "ipc": "G06F13/42", "assignees": ["NVIDIA CORPORATION"], "jurisdiction": "US"},
        {"pn": "US20260241559A1", "title": "Generalizable mobility model for robotic systems", "date": "2026-08-20", "legal_status": "pending", "ipc": "B25J9/16", "assignees": ["NVIDIA CORPORATION"], "jurisdiction": "US"},
        {"pn": "US20260246761A1", "title": "Cloud-hosted management for edge computing devices", "date": "2026-08-20", "legal_status": "pending", "ipc": "H04L9/40", "assignees": ["NVIDIA CORPORATION"], "jurisdiction": "US"},
        {"pn": "US20260245325A1", "title": "Teleportation system combining virtual reality and augmented reality", "date": "2026-08-20", "legal_status": "pending", "ipc": "G06T19/20", "assignees": ["NVIDIA CORPORATION"], "jurisdiction": "US"},
        {"pn": "US20260245346A1", "title": "Synthetic eye image generation using neural networks", "date": "2026-08-20", "legal_status": "pending", "ipc": "G06V10/774", "assignees": ["NVIDIA CORPORATION"], "jurisdiction": "US"},
        {"pn": "US20260245574A1", "title": "Cache-based streaming speaker diarization", "date": "2026-08-20", "legal_status": "pending", "ipc": "G10L21/0308", "assignees": ["NVIDIA CORPORATION"], "jurisdiction": "US"},
        {"pn": "US20260245547A1", "title": "Query-less speaker targeting", "date": "2026-08-20", "legal_status": "pending", "ipc": "G10L15/16", "assignees": ["NVIDIA CORPORATION"], "jurisdiction": "US"},
        {"pn": "DE102026105722A1", "title": "EFFICIENT VALIDATION AND RESYNCING OF TIMESERIES DATA IN MULTI-SENSOR SYSTEMS", "date": "2026-08-20", "legal_status": "pending", "ipc": "G06F18/20", "assignees": ["NVIDIA CORPORATION"], "jurisdiction": "DE"},
        {"pn": "US20260241954A1", "title": "Surface sensing", "date": "2026-08-20", "legal_status": "pending", "ipc": "B60W60/00", "assignees": ["NVIDIA CORPORATION"], "jurisdiction": "US"},
        {"pn": "DE102025133035A1", "title": "Improved double-edge data bus inversion to reduce IR falloff", "date": "2026-08-20", "legal_status": "pending", "ipc": "G06F13/42", "assignees": ["NVIDIA CORPORATION"], "jurisdiction": "DE"},
    ], [
        {"title": "Frame-Stacked Local Transformers for Efficient Multi-Codebook Speech Generation", "authors": ["Fejgin, Roy", "Neekhara, Paarth", "Yang, Xuesong", "Casanova, Edresson", "Langman, Ryan", "Kim, Jaehyeon", "Ghosh, Subhankar", "Hussain, Shehzeen", "Li, Jason"], "org": "NVIDIA", "date": "2026-05-03", "journal": "ArXiv", "doi": "10.1109/icassp55912.2026.11462920", "cited_count": 0},
        {"title": "How Does Instrumental Music Help Singfake Detection?", "authors": ["Chen, Xuanjun", "Hu, Chia-Yu", "Lin, I-Ming", "Lin, Yi-Cheng", "Chiu, I-Hsiang", "Zhang, You", "Huang, Sung-Feng", "Yang, Yi-Hsuan", "Wu, Haibin", "Jang, Jyh-Shing Roger"], "org": "NTU / University of Rochester / CMU / NVIDIA", "date": "2026-05-03", "journal": "ArXiv", "doi": "10.1109/icassp55912.2026.11460829", "cited_count": 0},
        {"title": "LoRAFusion: Efficient LoRA Fine-Tuning for LLMs", "authors": ["Zhu, Zhanda", "Su, Qidong", "Ding, Yaoyao", "Song, Kevin", "Wang, Shang", "Pekhimenko, Gennady"], "org": "Vector Institute / University of Toronto / NVIDIA", "date": "2026-04-26", "journal": "ArXiv", "doi": "10.1145/3767295.3769331", "cited_count": 0},
        {"title": "Taming the Long-Tail: Efficient Reasoning RL Training with Adaptive Drafter", "authors": ["Hu, Qinghao", "Yang, Shang", "Guo, Junxian", "Yao, Xiaozhe", "Lin, Yujun", "Gu, Yuxian", "Cai, Han", "Gan, Chuang", "Klimovic, Ana", "Han, Song"], "org": "ETH Zurich / UMass Amherst", "date": "2026-03-22", "journal": "ArXiv", "doi": "10.1145/3779212.3790231", "cited_count": 0},
        {"title": "MapTune: Versatile ASIC Technology Mapping via Reinforcement Learning Guided Library Tuning", "authors": ["Liu, Mingju", "Robinson, Daniel", "Li, Yingjie", "Maximilian Kuehn, Johannes", "Liang, Rongjian", "Ren, Haoxing", "Yu, Cunxi"], "org": "University of Maryland / MIT / NVIDIA", "date": "2026-03-20", "journal": "ACM TODAES", "doi": "10.1145/3748507", "cited_count": 4},
        {"title": "Data-Driven Loss Functions for Inference-Time Optimization in Text-to-Image", "authors": ["Yiflach, Sapir Esther", "Atzmon, Yuval", "Chechik, Gal"], "org": "NVIDIA / Bar-Ilan University", "date": "2026-03-06", "journal": "ArXiv", "doi": "10.1109/wacv61042.2026.00344", "cited_count": 0},
        {"title": "TA-Prompting: Enhancing Video Large Language Models for Dense Video Captioning via Temporal Anchors", "authors": ["Cheng, Wei-Yuan", "Chang, Kai-Po", "Huang, Chi-Pin", "Yang, Fu-En", "Wang, Yu-Chiang Frank"], "org": "NTU / NVIDIA", "date": "2026-03-06", "journal": "ArXiv", "doi": "10.1109/wacv61042.2026.00030", "cited_count": 0},
        {"title": "gpuPairHMM: High-Speed Pair-HMM Forward Algorithm for DNA Variant Calling on GPUs", "authors": ["Schmidt, Bertil", "Kallenborn, Felix", "Wichmann, Alexander", "Chacon, Alejandro", "Hundt, Christian"], "org": "JGU Mainz / NVIDIA", "date": "2026-03-01", "journal": "IEEE TCBB", "doi": "10.1109/tcbbio.2026.3657252", "cited_count": 0},
    ]),
]

if __name__ == "__main__":
    for company, patents, papers in DATA:
        ok = import_ip_assets(company, patents=patents, papers=papers)
        print(f"[{'OK' if ok else 'FAIL'}] {company}: 专利 {len(patents)} / 论文 {len(papers)}")
