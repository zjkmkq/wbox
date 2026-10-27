"""wbox.ascii_names —— 路径组件 ASCII 化：中文目录名 → 拼音/英文。

铁律（2026-10-25 用户实测确认，写死不许绕）：
DevEco Studio / hvigor 无法识别中文目录。WBox 生成的一切路径组件——
工程目录、解包目录（work/）、鸿蒙工程目录、rawfile 资源目标——必须 ASCII。
转换规则（用户钦定）：中文转拼音；"或者直接取其首字母的拼音"作为降级，
即本表覆盖常用字取全拼，未覆盖的字丢弃，全丢空时兜底 "app"。

覆盖策略：内置常用字表（游戏/工具/办公类应用名高频字为主，约 1500 字）。
表外字直接丢弃；若丢弃导致空名，兜底 "app" + 原文哈希 4 位，保唯一。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

# ---------------------------------------------------------------- 拼音表
# 紧凑存法："拼音字" 对以空格分隔（拼音在前、汉字在后），加载时解析。
# 无声调小写；ü 写作 v（nv=女，ASCII 友好）。多音字取最常用读音，
# 重复条目后者生效（字典覆盖）——目录名只求确定可复现，不求方言准确。
_PINYIN_PAIRS = """
a阿 ai爱 an安 ang昂 ao奥 ba八 ba巴 ba把 ba爸 ba百 ba白 bai摆 bai败 bai拜
ban班 ban般 ban板 ban版 ban办 ban半 ban伴 bang帮 bang棒 bao包 bao宝 bao保
bao报 bao抱 bao暴 bao爆 bao薄 bei杯 bei悲 bei北 bei背 bei被 bei倍 ben奔
ben本 ben笨 bi逼 bi比 bi彼 bi笔 bi币 bi必 bi边 bian编 bian变 bian遍 biao标
biao表 bie别 bin宾 bin兵 bing冰 bing并 bing病 bo波 bo播 bo博 bo薄 bu不
bu布 bu步 bu部 can参 can残 can惨 cang仓 cang藏 cao操 cao槽 cao草 ce侧
ce册 ceng层 cha插 cha茶 cha查 cha差 chai拆 chan产 chan颤 chang昌 chang长
chang常 chang场 chang唱 chao超 chao朝 chao炒 che车 che彻 che撤 chen沉
chen陈 chen晨 chen称 cheng称 cheng成 cheng城 cheng乘 cheng程 cheng惩
chi吃 chi池 chi持 chi尺 chi齿 chong冲 chong充 chou抽 chou愁 chu出 chu初
chu除 chu储 chu处 chu触 chuan川 chuan传 chuan船 chuang窗 chuang床
chuang创 chui吹 chui垂 chun春 chun纯 ci词 ci次 ci慈 cong从 cong丛 cu粗
cu促 cui摧 cui翠 cun村 cun存 cuo错 da答 da打 da大 da达 dai呆 dai带
dai待 dai贷 dai代 dan丹 dan单 dan担 dan胆 dan但 dan淡 dan蛋 dang当
dang档 dang挡 dao刀 dao导 dao倒 dao到 dao盗 de得 de的 de德 dei登 deng灯
deng等 di低 di滴 di敌 di底 di地 di弟 di帝 di第 dian颠 dian典 dian点
dian电 dian店 diao雕 diao掉 diao钓 die跌 die叠 ding丁 ding顶 ding定
diu丢 dong东 dong冬 dong动 dong冻 dong洞 dou都 dou斗 dou豆 dou逗 du督
du独 du读 du度 du肚 du渡 duan端 duan短 duan断 dui堆 dui队 dui对 dun吨
dun顿 duo多 duo夺 duo朵 e饿 e恶 e噩 en恩 er儿 er二 er耳 fa发 fa法
fa翻 fan凡 fan反 fan犯 fan饭 fan范 fang方 fang防 fang房 fang纺 fang访
fang放 fei飞 fei非 fei肥 fei废 fen分 fen芬 fen粉 fen奋 fen份 feng丰
feng风 feng封 feng峰 feng锋 feng蜂 feng疯 feng逢 feng凤 fo佛 fou否
fu夫 fu肤 fu孵 fu服 fu浮 fu符 fu辐 fu福 fu抚 fu府 fu辅 fu父 fu付 fu负
fu妇 fu附 fu复 fu副 fu富 fu赴 gai该 gai改 gai概 gan干 gan甘 gan杆 gan肝
gan赶 gan敢 gan感 gan刚 gang冈 gang港 gao高 gao搞 gao稿 gao告 ge哥
ge歌 ge戈 ge割 ge格 ge隔 ge个 ge各 ge给 gen根 gen跟 geng更 geng耕
gong工 gong弓 gong公 gong功 gong攻 gong供 gong宫 gou勾 gou沟 gou狗
gou购 gou够 gu古 gu谷 gu股 gu骨 gu鼓 gu故 gu顾 gu固 gua刮 gua挂 guai拐
guai怪 guan关 guan观 guan官 guan管 guan惯 guan馆 guang光 guang广 gui归
gui龟 gui规 gui鬼 gui柜 gui贵 gui桂 gun滚 guo锅 guo国 guo果 guo过
guo裹 ha哈 hai还 hai孩 hai海 han含 han寒 han喊 han汉 han汗 hang航
hao毫 hao好 hao号 hao豪 he喝 he和 he何 he河 he荷 he核 he盒 he贺 hei黑
hen很 hen恨 heng横 heng恒 hong轰 hong红 hong宏 hong洪 hou侯 hou厚
hou候 hu呼 hu忽 hu狐 hu胡 hu湖 hu壶 hu互 hu户 hu护 hua花 hua华 hua滑
hua化 hua画 hua话 huai怀 huai坏 huan欢 huan还 huan环 huan缓 huan换
huan患 huang荒 huang皇 huang黄 huang晃 hui灰 hui挥 hui辉 hui回 hui汇
hui会 hui绘 hui慧 hui惠 hun婚 hun混 huo火 huo或 huo货 huo获 huo祸
huo惑 ji击 ji机 ji鸡 ji积 ji基 ji激 ji及 ji吉 ji级 ji即 ji极 ji急
ji疾 ji集 ji籍 ji几 ji己 ji挤 ji计 ji记 ji技 ji际 ji济 ji继 ji寄 ji加
ji嘉 jia夹 jia家 jia佳 jia甲 jia驾 jia架 jia假 jia价 jia嫁 jian尖
jian坚 jian间 jian艰 jian检 jian减 jian简 jian见 jian件 jian建 jian健
jian渐 jian鉴 jian箭 jiang江 jiang将 jiang讲 jiang酱 jiang降 jiang僵
jiao交 jiao郊 jiao娇 jiao浇 jiao焦 jiao蕉 jiao角 jiao饺 jiao脚 jiao叫
jiao教 jiao较 jiao接 jiao街 jie阶 jie接 jie揭 jie节 jie杰 jie结 jie截
jie解 jie届 jie戒 jie界 jie借 jin今 jin斤 jin金 jin津 jin仅 jin紧
jin锦 jin尽 jin劲 jin近 jin进 jing京 jing经 jing惊 jing晶 jing精
jing鲸 jing井 jing景 jing警 jing竞 jing净 jing静 jing境 jing镜 jiu九
jiu久 jiu酒 jiu旧 jiu救 jiu就 jiu舅 ju居 ju局 ju桔 ju菊 ju锯 ju举
ju巨 ju句 ju具 ju惧 ju剧 ju据 ju距 ju聚 juan捐 juan卷 jue决 jue绝
jue角 jue掘 jun军 jun均 jun君 ka咖 ka卡 kai开 kai凯 kan看 kan堪
kan砍 kang康 kang扛 kang抗 kao考 kao烤 ke科 ke可 ke渴 ke克 ke刻
ke客 ke肯 ke空 kong空 kong孔 kou口 kou扣 ku枯 ku苦 ku库 ku裤 kua夸
kua跨 kuai快 kuai块 kuan宽 kuang狂 kui亏 kui窥 kun昆 kun困 kuo扩
kuo阔 la拉 la喇 la辣 la腊 la啦 lai来 lai赖 lan兰 lan蓝 lan览 lan懒
lan烂 lang狼 lang朗 lao老 lao劳 lao牢 le乐 le了 le勒 lei雷 lei累
lei类 leng冷 li利 li立 li丽 li励 li例 li隶 li力 li历 li厉 li吏 li璃
li哩 li俩 lian连 lian怜 lian帘 lian莲 lian联 lian廉 lian脸 lian练
lian炼 liang两 liang亮 liang凉 liang量 liao聊 liao疗 liao辽 lie列
lie烈 lie猎 lin邻 lin林 lin临 lin淋 lin琳 ling灵 ling岭 ling零
ling铃 ling龄 ling领 ling令 liu六 liu流 liu留 liu刘 liu柳 long龙
long隆 lou楼 lou漏 lou露 lu卢 lu芦 lu炉 lu鲁 lu陆 lu录 lu鹿 lu路
lu驴 lv旅 lv铝 lv律 lv率 lv绿 luan乱 lue略 lun轮 lun论 luo罗 luo萝
luo逻 luo锣 luo骆 luo落 ma妈 ma马 ma码 ma蚂 ma骂 ma吗 mai埋 mai买
mai卖 mai麦 man满 man漫 man慢 mang忙 mao毛 mao矛 mao茅 mao冒 mao帽
me么 mei没 mei眉 mei梅 mei媒 mei煤 mei每 mei美 mei妹 mei魅 men门
men们 meng蒙 meng盟 meng猛 meng梦 mi弥 mi迷 mi谜 mi米 mi秘 mi密
mian棉 mian免 mian面 miao苗 miao秒 miao描 miao妙 miao庙 mie灭 min民
min敏 ming名 ming明 ming命 ming鸣 miu谬 mo摸 mo模 mo膜 mo摩 mo魔
mo抹 mo末 mo沫 mo陌 mou某 mu母 mu木 mu目 mu牧 mu墓 mu幕 na那 na纳
na娜 na哪 nai奶 nai耐 nan男 nan南 nan难 nang囊 nao挠 nao脑 nao闹
ne呢 nei内 neng能 ni尼 ni泥 ni你 ni拟 ni逆 nv女 nian年 nian念
niang娘 niao鸟 nie捏 nin您 ning宁 ning凝 niu牛 niu扭 nong农 nong浓
nong弄 nu努 nu怒 nuan暖 nuo诺 ou欧 ou偶 pa爬 pa怕 pa拍 pai排 pai派
pan攀 pan盘 pan判 pang旁 pang胖 pao抛 pao跑 pao炮 pao泡 pei陪 pei培
pei配 pen喷 pen盆 peng朋 peng棚 peng鹏 peng捧 pi批 pi披 pi疲 pi皮
pi匹 pi屁 pian片 pian偏 pian骗 piao飘 piao票 pie撇 pin拼 pin贫 pin品
ping平 ping评 ping凭 ping屏 po坡 po泼 po迫 po破 pou剖 pu扑 pu铺
pu朴 pu普 pu谱 qi七 qi齐 qi其 qi奇 qi骑 qi棋 qi旗 qi起 qi气 qi汽
qi弃 qi器 qi恰 qian千 qian钱 qian前 qian潜 qian浅 qian遣 qiang枪
qiang强 qiang墙 qiao乔 qiao桥 qiao巧 qiao俏 qie切 qie且 qie窃 qin亲
qin琴 qin勤 qin青 qing轻 qing倾 qing清 qing情 qing晴 qing请 qing庆
qiong穷 qiu秋 qiu求 qiu球 qu区 qu曲 qu屈 qu躯 qu取 qu去 qu趣 quan全
quan泉 quan拳 quan犬 quan劝 que缺 que却 que确 que雀 qun群 qun裙
ran然 rang让 rao绕 re热 re惹 ren人 ren仁 ren认 ren任 ren韧 reng仍
ri日 rong容 rong荣 rong融 rong柔 rou肉 ru如 ru入 ru软 ru锐 rui瑞
run润 ruo若 sa撒 sai赛 sai塞 san三 san散 san伞 sang桑 sang丧 sang嗓
sao扫 sao骚 se色 se涩 sen森 seng僧 sha杀 sha沙 sha纱 sha傻 shai晒
shan山 shan删 shan衫 shan闪 shan陕 shan善 shan扇 shan擅 shang商
shang上 shang尚 shao烧 shao稍 shang赏 she奢 she舌 she蛇 she设 she社
she射 she摄 shen申 shen身 shen深 shen神 shen审 shen甚 shen肾 shen渗
shen什 sheng升 sheng生 sheng声 sheng绳 sheng省 sheng圣 sheng胜
shi十 shi石 shi时 shi识 shi实 shi食 shi史 shi使 shi始 shi示 shi世
shi市 shi式 shi势 shi事 shi试 shi士 shi视 shi饰 shi室 shi是 shi适
shi释 shi誓 shou收 shou手 shou守 shou首 shou受 shou授 shou售 shou瘦
shu书 shu舒 shu输 shu蔬 shu熟 shu暑 shu属 shu术 shu述 shu树 shu束
shu数 shua刷 shuai衰 shuai摔 shuai帅 shuang双 shui水 shui睡 shui谁
shun瞬 shuo说 si丝 si司 si私 si思 si斯 si死 si四 si寺 si似 si松
si送 song宋 sou搜 sou艘 su苏 su俗 su速 su素 su诉 su肃 suan酸 suan算
sui虽 sui随 sui碎 sun孙 sun损 suo缩 suo所 suo锁 ta他 ta它 ta她
ta踏 ta塔 tai台 tai太 tai态 tai泰 tai贪 tan摊 tan坛 tan谈 tan弹
tan探 tan叹 tang汤 tang糖 tang堂 tang塘 tang躺 tao涛 tao掏 tao逃
tao桃 tao陶 te特 teng腾 ti提 ti题 ti蹄 ti体 ti替 tian天 tian田
tian甜 tian填 tiao挑 tiao条 tiao跳 tie铁 tie贴 ting厅 ting听 ting停
ting亭 ting挺 tong通 tong同 tong童 tong铜 tong统 tong痛 tou偷
tou头 tou投 tu突 tu图 tu徒 tu涂 tu土 tu吐 tu兔 tuan团 tui推 tui退
tun吞 tun屯 tuo拖 tuo脱 tuo驼 wa挖 wa娃 wa瓦 wa袜 wai外 wan弯
wan玩 wan完 wan晚 wan万 wan腕 wang王 wang网 wang往 wang忘 wang望
wei危 wei威 wei微 wei为 wei围 wei违 wei唯 wei维 wei伟 wei伪 wei尾
wei委 wei卫 wei未 wei位 wei味 wei畏 wei胃 wei谓 wei喂 wei尉 wen温
wen文 wen纹 wen蚊 wen闻 wen稳 wen问 weng翁 wo我 wo卧 wo握 wo沃
wu乌 wu污 wu屋 wu无 wu吴 wu五 wu武 wu舞 wu务 wu物 wu误 wu悟 wu雾
wu亡 xi夕 xi西 xi吸 xi希 xi昔 xi惜 xi稀 xi息 xi悉 xi习 xi席 xi洗
xi喜 xi戏 xi系 xi细 xi隙 xia下 xia夏 xia吓 xian先 xian纤 xian鲜
xian闲 xian贤 xian咸 xian衔 xian险 xian现 xian限 xian线 xian宪
xian陷 xiang相 xiang香 xiang乡 xiang详 xiang想 xiang向 xiang项
xiang巷 xiang象 xiang像 xiao消 xiao销 xiao萧 xiao小 xiao孝 xiao校
xiao效 xiao笑 xie些 xie歇 xie协 xie邪 xie胁 xie斜 xie谐 xie鞋
xie写 xie谢 xie泄 xie屑 xie械 xin心 xin辛 xin欣 xin新 xin薪 xin信
xing兴 xing星 xing刑 xing行 xing形 xing型 xing醒 xing幸 xing性
xing姓 xiong兄 xiong凶 xiong胸 xiong雄 xiu休 xiu修 xiu羞 xiu秀
xiu袖 xu须 xu虚 xu需 xu徐 xu许 xu序 xu叙 xu绪 xu续 xu絮 xu蓄
xu宣 xu玄 xu悬 xu旋 xu选 xue学 xue穴 xue雪 xue血 xun寻 xun巡 xun询
xun循 xun训 xun迅 ya压 ya鸭 ya牙 ya芽 ya雅 ya亚 yan烟 yan延 yan严
yan言 yan岩 yan炎 yan研 yan盐 yan颜 yan眼 yan演 yan厌 yan宴 yan验
yan艳 yang阳 yang杨 yang扬 yang羊 yang洋 yang仰 yang养 yang氧
yang样 yao妖 yao腰 yao邀 yao摇 yao遥 yao咬 yao药 yao要 ye爷 ye野
ye业 ye叶 ye页 ye夜 yi一 yi衣 yi医 yi依 yi伊 yi仪 yi宜 yi移 yi遗
yi疑 yi乙 yi已 yi以 yi蚁 yi义 yi亿 yi艺 yi议 yi亦 yi异 yi役 yi抑
yi易 yi益 yi谊 yi逸 yi意 yi毅 yi翼 yi因 yin音 yin阴 yin银 yin引
yin隐 yin印 ying应 ying英 ying婴 ying鹰 ying迎 ying盈 ying营
ying影 ying映 ying硬 yong拥 yong永 yong勇 yong涌 yong用 yong优
you优 you尤 you由 you邮 you犹 you游 you友 you有 you又 you右 you幼
you诱 yu于 yu与 yu予 yu余 yu鱼 yu娱 yu语 yu雨 yu羽 yu玉 yu域
yu喻 yu育 yu预 yu遇 yu愈 yu誉 yu浴 yu寓 yu裕 yuan元 yuan园 yuan原
yuan圆 yuan援 yuan缘 yuan源 yuan远 yuan愿 yuan怨 yue月 yue岳 yue阅
yue悦 yun云 yun允 yun运 yun韵 za杂 zai灾 zai载 zai再 zai在 zan咱
zan暂 zang脏 zang藏 zao遭 zao早 zao澡 zao噪 zao造 ze责 ze泽 zei贼
zeng增 zha扎 zha砸 zha榨 zhai摘 zhai宅 zhan占 zhan战 zhan站
zhan绽 zhang张 zhang章 zhang长 zhang涨 zhang掌 zhang账 zhao招
zhao着 zhao找 zhao召 zhao照 zhe遮 zhe折 zhe哲 zhe这 zhen真 zhen针
zhen诊 zhen阵 zhen振 zhen镇 zheng争 zheng征 zheng睁 zheng蒸 zheng整
zheng正 zheng证 zheng政 zheng症 zhi之 zhi支 zhi汁 zhi枝 zhi知 zhi织
zhi肢 zhi脂 zhi执 zhi直 zhi值 zhi职 zhi植 zhi殖 zhi止 zhi旨 zhi纸
zhi指 zhi趾 zhi至 zhi志 zhi制 zhi质 zhi治 zhi致 zhi秩 zhi智 zhi置
zhi稚 zhong中 zhong忠 zhong终 zhong钟 zhong种 zhong肿 zhong众
zhou州 zhou舟 zhou周 zhou洲 zhou粥 zhou宙 zhou昼 zhu朱 zhu猪 zhu诸
zhu竹 zhu烛 zhu逐 zhu主 zhu煮 zhu住 zhu助 zhu注 zhu驻 zhua抓
zhuan专 zhuan砖 zhuan转 zhuan赚 zhuang装 zhuang壮 zhuang状 zhui追
zhun准 zhuo捉 zhuo桌 zhuo卓 zi姿 zi资 zi滋 zi子 zi字 zi自 zong踪
zong总 zou走 zou奏 zu租 zu足 zu族 zu组 zu祖 zu钻 zuan钻 zui最 zui罪
zun尊 zuo作 zuo坐 zuo座 zuo做
"""

# 解析：每对 "拼音字"——末位是汉字，前面是拼音
_PINYIN: dict[str, str] = {}
for _pair in _PINYIN_PAIRS.split():
    if len(_pair) >= 2:
        _PINYIN[_pair[-1]] = _pair[:-1]

# CJK 基本区 + 兼容区 + 々/假名/韩文（表外字符一并按丢弃处理）
_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3005\u3040-\u30ff\uac00-\ud7af]")
_NON_ASCII_KEEP = re.compile(r"[^A-Za-z0-9_.-]+")


def ascii_name(name: str) -> str:
    """任意字符串 → ASCII 目录/文件名组件。

    中文取拼音全拼（内置表）；表外 CJK 与其他非 ASCII 字符丢弃；
    空结果兜底 "app" + 原文哈希 4 位。幂等：ASCII 输入原样归一化返回。
    """
    text = str(name or "")
    out: list[str] = []
    for ch in text:
        if ch.isascii():
            out.append(ch)
        elif ch in _PINYIN:
            out.append(_PINYIN[ch])
        # 表外字：无声丢弃（用户钦定降级策略）
    result = _NON_ASCII_KEEP.sub("", "".join(out))
    result = re.sub(r"_+", "_", result).strip("_")
    if not result:
        digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:4]
        return f"app{digest}"
    if not any(c.isalpha() for c in result):
        # 只剩数字/符号（如 "123"）时补哈希，防裸数字目录歧义
        digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:4]
        return f"{result}_{digest}"
    return result


def ascii_initials(name: str) -> str:
    """任意字符串 → ASCII 短名：中文取拼音首字母（圆锯→yj），其余同 ascii_name。

    用户钦定（2026-10-25）：解包目录/工程名用首字母，全拼太长
    （92934圆锯模拟器8 → 92934yjmq8，全拼是 92934yuanjumoniqi8）。
    """
    text = str(name or "")
    out: list[str] = []
    for ch in text:
        if ch.isascii():
            out.append(ch)
        elif ch in _PINYIN:
            out.append(_PINYIN[ch][:1])
        # 表外字：无声丢弃
    result = _NON_ASCII_KEEP.sub("", "".join(out))
    result = re.sub(r"_+", "_", result).strip("_")
    if not result:
        digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:4]
        return f"app{digest}"
    if not any(c.isalpha() for c in result):
        # 只剩数字/符号（如 "123"）时补哈希，防裸数字目录歧义
        digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:4]
        return f"{result}_{digest}"
    return result


def work_dir_name(apk_stem: str) -> str:
    """APK 文件名（去扩展名）→ 解包目录名（ASCII，拼音首字母，2026-10-25 用户钦定）。

    输入应已去扩展名；此处不再二次 stem（防 "跳石子_1.1" 被剥成 "跳石子_1"）。
    """
    return ascii_initials(str(apk_stem))


def non_ascii_parts(path: str | Path) -> list[str]:
    """返回路径中的非 ASCII 组件列表（空列表 = 干净）。"""
    return [part for part in Path(path).parts if part and not part.isascii()]


def is_ascii_path(path: str | Path) -> bool:
    return not non_ascii_parts(path)


def harmony_default_dir(project_dir: str | Path, app_name: str) -> tuple[Path, str]:
    """鸿蒙工程默认输出目录（返回 (目录, 提示)）。

    DevEco Studio 不认中文目录（2026-10-25 实测确认）：工程目录本身含非
    ASCII 时，不能把鸿蒙工程放 <project>/harmony/ 里——绝对路径照样带中文。
    此时落到工程同级 ASCII 目录 <project.parent>/harmony/<英文名>；
    seal_step 的探测顺序（<project>/harmony/*、上级 harmony/*）已覆盖，
    GUI 侧能自动找到。父目录也带中文时只能放工程内，明确警告。
    """
    project = Path(project_dir)
    inside = project / "harmony" / ascii_name(app_name)
    if is_ascii_path(inside):
        return inside, ""
    if not is_ascii_path(project.parent):
        return inside, (f"工程目录 {project} 含非 ASCII 字符，DevEco Studio 可能无法打开"
                        f"其中的鸿蒙工程；建议把整个工程移到英文目录")
    sibling = project.parent / "harmony" / ascii_name(app_name)
    note = (f"工程目录 {project.name} 含中文，鸿蒙工程改输出到同级英文目录：{sibling}"
            f"（DevEco Studio 不识别中文目录）")
    return sibling, note


def unique_dir(path: Path) -> Path:
    """已存在则追加 _2/_3…，避免覆盖别的工程。"""
    if not path.exists():
        return path
    for i in range(2, 100):
        cand = path.with_name(f"{path.name}_{i}")
        if not cand.exists():
            return cand
    return path
