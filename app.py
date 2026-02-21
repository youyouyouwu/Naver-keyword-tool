import streamlit as st
import google.generativeai as genai
import pandas as pd
import time
import os
import re
import requests
import hashlib
import hmac
import base64

# ==========================================
# 1. 页面配置与后台 Secrets 检查
# ==========================================
st.set_page_config(page_title="LxU 全链路决策系统", layout="wide")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")
NAVER_API_KEY = st.secrets.get("API_KEY")
NAVER_SECRET_KEY = st.secrets.get("SECRET_KEY")
NAVER_CUSTOMER_ID = st.secrets.get("CUSTOMER_ID")

if not all([GEMINI_API_KEY, NAVER_API_KEY, NAVER_SECRET_KEY, NAVER_CUSTOMER_ID]):
    st.error("⚠️ 缺少 API 密钥！请确保在 .streamlit/secrets.toml 中配置了所有必需的 Key。")
    st.stop()

# 初始化配置
genai.configure(api_key=GEMINI_API_KEY)
SECRET_KEY_BYTES = NAVER_SECRET_KEY.encode("utf-8")
NAVER_API_URL = "https://api.searchad.naver.com/keywordstool"

# ==========================================
# 2. 核心大模型指令 (Prompts)
# ==========================================
PROMPT_STEP_1 = """
你是一个精通韩国 Coupang 运营的 SEO 专家，品牌名为 LxU。

第一，我是一个在韩国做coupang平台的跨境电商卖家，这是我的产品详情页，我现在需要后台找出20个产品关键词输入到后台以便让平台快速准确的为我的产品打上准确的标签匹配流量。请帮我找到或者推测出这些符合本地搜索习惯的韩文关键词。在分析产品的同时也综合考虑推荐商品中类似产品的标题挖掘关键词（需要20个后台设置的关键词，不包含品牌词）
输出要求：
1.保留竖版序号排列外加策略解释的版本，含翻译文。
2.还需要输出一款逗号隔开的版本方便在coupang后台录入。

第二，我是一个精铺，推广侧率为前期少量进货快速付费推广测品的卖家。找精准长尾词做付费推广（需要精准流量词，按相关性排列并打分1-5）。
广告组一为【核心出单词】。
广告组二为【精准长尾关键词】（尽量挖掘30个左右，包含缩写如'스뎅'、语序颠倒、场景词、关联竞品如Daiso等）。
广告组三为【长尾捡漏组广告词】（低CPC、购买意向强、Low Traffic。包含错别字、缩写、方言等变体）。
输出格式：Excel表格形式【序号 | 韩文关键词 | 中文翻译 | 策略类型 | 预估流量(High/Medium/Low) | 相关性评分】。

第三，生成一个高点击率 (High CTR) 标题方案：公式 [品牌名] + [直击痛点形容词] + [核心差异化卖点] + [核心大词] + [核心属性/材质] + [场景/功能]。20个字以内，符合韩国人可读性。

第四，提供一个产品韩语名称用于内部管理。

第五，按照产品卖点撰写5条商品好评，语法自然、风格各异，本土化表达，表格形式排列。

第六，将上述三个广告组的所有关键词进行去重汇总，单列纵向列表输出表格。

第七，AI 主图生成建议：基于场景词建议背景和构图，主图严禁带文字。

【程序读取专属指令 - 极度重要】：
为了方便我的系统自动抓取，请务必将“第六部分”的最终去重汇总关键词，放在以下两个标记之间输出！每行只写一个韩文关键词，尽量不要带中文或序号。
[LXU_KEYWORDS_START]
(在这里填入纯韩文关键词)
[LXU_KEYWORDS_END]
"""

PROMPT_STEP_3 = """
你是一位拥有10年实战经验的韩国 Coupang 跨境电商运营专家，精通韩语语义分析、VOC挖掘以及“精铺快速测品”的高 ROAS 广告策略。我们做的是韩国电商coupang平台，但我是一个中国卖家，输出我能看懂的结果。关键词相关内容不要翻译英文，保持韩文，只要有对应的中文示意即可。

**核心任务：**
用户提供了“产品详情页原图”及“Naver关键词客观搜索量数据”。你需要基于产品特性和真实数据表现，输出精准广告分组、否定词表。所有关于关键词的分析不要含有 LxU 的品牌词。

以下是刚抓取到的客观市场搜索量数据（CSV格式）：
{market_data}

**第一步：全维度分析 (Deep Analysis)**
1. 视觉与属性识别： 分析详情页信息，锁定核心属性（材质、形状、功能、场景）。
2. 痛点挖掘： 从竞品差评中提炼用户痛点（如：噪音大、易生锈）。
3. 排除逻辑建立： 明确“绝对不相关”的属性（如：产品是塑料，排除“不锈钢”）。

**第二步：关键词清洗与打分 (Filtering & Scoring)**
基于我提供的数据列表，进行严格筛选：
1. 相关性打分 (1-5分)：
   * 1-2分 (保留)： 核心词及精准长尾词。
   * 3分 (保留)： 强关联场景或竞品词（可用于捡漏）。
   * 4-5分 (剔除/否定)： 宽泛大词或属性错误的词。
2. 流量与痛点加权：优先保留能解决“痛点”的词。参考“总搜索量”，保留虽然流量小但极精准的长尾词。

**第三步：输出二大模块 (Output Modules)**

**模块一：付费广告投放策略表** (请以 Markdown 表格输出)
* **广告组分类：**
   * 【核心出单词】：流量较大，完全匹配。浏览量从高到低排列。
   * 【精准长尾词】：核心词+具体属性。浏览量从高到低排列。
   * 【捡漏与痛点组】：错别字、倒序、方言、场景词、竞品词。
   * 给关键词标记序号。单独成列。浏览量从高到低排列。
   * 按分类制作三组关键词结果列表。保证准确的情况下尽量保证关键词数量。

**模块二：否定关键词列表 (Negative Keywords)**
*用于广告后台屏蔽，防止无效烧钱。*
* **建议屏蔽的词：** `[词1], [词2], [词3]...`
* **屏蔽原因：** [简述，例如：材质不符、场景错误等]
"""

# ==========================================
# 3. Naver 数据抓取引擎
# ==========================================
def clean_for_api(keyword: str) -> str:
    return re.sub(r"\s+", "", keyword)

def make_signature(method: str, uri: str, timestamp: str) -> str:
    message = f"{timestamp}.{method}.{uri}".encode("utf-8")
    signature = hmac.new(SECRET_KEY_BYTES, message, hashlib.sha256).digest()
    return base64.b64encode(signature).decode("utf-8")

def normalize_count(raw):
    if isinstance(raw, int): return raw
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("<"): return 5
        if s.startswith(">"):
            num = s[1:].strip()
            return int(num) if num.isdigit() else 0
        s = s.replace(",", "")
        if s.isdigit(): return int(s)
    return 0

def fetch_naver_data(main_keywords, progress_bar, status_text):
    all_rows = []
    total = len(main_keywords)
    
    for i, mk in enumerate(main_keywords, start=1):
        status_text.text(f"📊 正在查询 Naver 搜索量 [{i}/{total}]: {mk}")
        progress_bar.progress(i / total)
        query_kw = clean_for_api(mk)
        
        try:
            timestamp = str(int(time.time() * 1000))
            sig = make_signature("GET", "/keywordstool", timestamp)
            headers = {
                "X-Timestamp": timestamp, "X-API-KEY": NAVER_API_KEY,
                "X-Customer": NAVER_CUSTOMER_ID, "X-Signature": sig
            }
            res = requests.get(NAVER_API_URL, headers=headers, params={"hintKeywords": query_kw, "showDetail": 1})
            
            if res.status_code == 200:
                data = res.json()
                if "keywordList" in data:
                    # 限制抓取深度，防止数据溢出，主词取前 8 个关联词
                    for item in data["keywordList"][:8]: 
                        pc = normalize_count(item.get("monthlyPcQcCnt", 0))
                        mob = normalize_count(item.get("monthlyMobileQcCnt", 0))
                        all_rows.append({
                            "提取主词": mk,
                            "Naver扩展词": item.get("relKeyword", ""),
                            "总搜索量(PC+Mob)": pc + mob,
                            "竞争度": item.get("compIdx", "-")
                        })
        except Exception as e:
            pass
        time.sleep(1) # API 保护频率
        
    df = pd.DataFrame(all_rows)
    if not df.empty:
        df = df.drop_duplicates(subset=["Naver扩展词"]).sort_values(by="总搜索量(PC+Mob)", ascending=False)
    return df

# ==========================================
# 4. 主 UI 与工作流控制
# ==========================================
st.title("⚡ LxU 自动化测品工厂 (终极闭环版)")
st.info("工作流：上传详情页 ➡️ Gemini提取初筛词 ➡️ Naver真实搜索量回测 ➡️ Gemini终极排兵布阵")

files = st.file_uploader("上传产品详情页 (PDF/PNG/JPG)", type=["pdf", "png", "jpg"], accept_multiple_files=True)

if files and st.button("🚀 启动全链路提炼"):
    model = genai.GenerativeModel(model_name="gemini-2.5-flash") # 建议用 Flash，速度快且不易报429
    
    for file in files:
        st.divider()
        st.header(f"📦 产品处理中：{file.name}")
        temp_path = f"temp_{file.name}"
        with open(temp_path, "wb") as f:
            f.write(file.getbuffer())
            
        # ------------------ 第一步：识图与提取 ------------------
        with st.status("🔍 第一步：大模型视觉提炼初筛词...", expanded=True) as s1:
            gen_file = genai.upload_file(path=temp_path)
            while gen_file.state.name == "PROCESSING":
                time.sleep(2)
                gen_file = genai.get_file(gen_file.name)
                
            res1 = model.generate_content([gen_file, PROMPT_STEP_1])
            
            with st.expander("👉 点击查看：第一步 AI 原始全量输出报告"):
                st.write(res1.text)
            
            # 暴力正则提取纯韩文
            match = re.search(r"\[LXU_KEYWORDS_START\](.*?)\[LXU_KEYWORDS_END\]", res1.text, re.DOTALL | re.IGNORECASE)
            kw_list = []
            if match:
                raw_block = match.group(1)
                extracted_words = re.findall(r'[가-힣]+', raw_block) # 只要韩文字符
                kw_list = list(dict.fromkeys(extracted_words))
            else:
                st.warning("⚠️ 未找到精准锚点，尝试从全文最后暴力抓取...")
                tail_text = res1.text[-800:]
                extracted_words = re.findall(r'[가-힣]+', tail_text)
                kw_list = list(dict.fromkeys(extracted_words))[:25]
                
            if kw_list:
                s1.update(label=f"✅ 第一步完成！成功截获 {len(kw_list)} 个纯韩文初筛词", state="complete")
                st.success(f"准备喂给 Naver 的词表：{kw_list}")
            else:
                s1.update(label="❌ 第一步提取失败，未能找到任何韩文", state="error")
                continue # 跳过该文件

        # ------------------ 第二步：Naver 回测 ------------------
        with st.status("📊 第二步：连接 Naver API 获取客观搜索量...", expanded=True) as s2:
            pb = st.progress(0)
            status_txt = st.empty()
            
            df_market = fetch_naver_data(kw_list, pb, status_txt)
            
            if not df_market.empty:
                st.dataframe(df_market) # 展示搜索量表格
                s2.update(label="✅ 第二步完成！真实市场数据已获取", state="complete")
            else:
                s2.update(label="❌ 第二步失败，Naver 未返回有效数据", state="error")
                st.error("请检查关键词是否过于生僻，或 Naver API 额度是否受限。")
                continue

        # ------------------ 第三步：终极策略决策 ------------------
        with st.status("🧠 第三步：AI 大脑综合决策 (合并数据与图像)...", expanded=True) as s3:
            # 将第二步查到的数据转成 CSV 文本，喂给大模型
            market_csv_string = df_market.to_csv(index=False) 
            final_prompt = PROMPT_STEP_3.format(market_data=market_csv_string)
            
            # 双重输入：PDF 文件对象 + 带有真实搜索量的 Prompt
            res3 = model.generate_content([gen_file, final_prompt])
            st.markdown("### 🏆 终极运营策略报告")
            st.success(res3.text)
            
            s3.update(label="✅ 第三步完成：终极排兵布阵已生成", state="complete")

        # ------------------ 收尾：清理与导出 ------------------
        os.remove(temp_path)
        try:
            genai.delete_file(gen_file.name) # 清理云端缓存
        except:
            pass
            
        final_report = f"【LxU 产品测品报告：{file.name}】\n\n" + "="*40 + "\n[第一步 AI 初筛原始结果]\n" + res1.text + "\n\n" + "="*40 + "\n[第二步 Naver 真实数据]\n" + market_csv_string + "\n\n" + "="*40 + "\n[第三步 终极策略排兵布阵]\n" + res3.text
        
        st.download_button(
            label=f"📥 一键下载 {file.name} 完整测品报告 (TXT)", 
            data=final_report, 
            file_name=f"LxU_测品全记录_{file.name}.txt"
        )
