import streamlit as st
import google.generativeai as genai
import pandas as pd
import time
import os
import re
import json
import requests
import hashlib
import hmac
import base64

# ==========================================
# 1. 页面配置与 Secrets 调用
# ==========================================
st.set_page_config(page_title="LxU 全链路决策系统", layout="wide")

# 获取所有需要的 API Keys
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", None)
NAVER_API_KEY = st.secrets.get("API_KEY", None)
NAVER_SECRET_KEY = st.secrets.get("SECRET_KEY", None)
NAVER_CUSTOMER_ID = st.secrets.get("CUSTOMER_ID", None)

if not all([GEMINI_API_KEY, NAVER_API_KEY, NAVER_SECRET_KEY, NAVER_CUSTOMER_ID]):
    st.error("⚠️ 缺少 API 密钥！请确保 Secrets 中配置了 GEMINI_API_KEY 以及 Naver 的三个参数。")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)
# Naver Secret 必须转成 bytes
SECRET_KEY_BYTES = NAVER_SECRET_KEY.encode("utf-8")
NAVER_API_URL = "https://api.searchad.naver.com/keywordstool"

# ==========================================
# 2. Prompts 定义 (融合你的最新策略)
# ==========================================
# 第一步 Prompt：提取初筛词，并严格要求 JSON 输出格式
PROMPT_STEP_1 = """
你是一个精通韩国 Coupang 运营的 SEO 专家，品牌名为 LxU。
第一，我是一个在韩国做coupang平台的跨境电商卖家，这是我的产品详情页，我现在需要后台找出20个产品关键词输入到后台以便让平台快速准确的为我的产品打上准确的标签匹配流量。请帮我找到或者推测出这些符合本地搜索习惯的韩文关键词。在分析产品的同时也综合考虑推荐商品中类似产品的标题挖掘关键词（需要20个后台设置的关键词，不包含品牌词）
输出要求：
1.保留竖版序号排列外加策略解释的版本，含翻译文。
2.还需要输出一款逗号隔开的版本方便在coupang后台录入。

【核心指令】：请务必在回答的最末尾，将你提取出的这20个韩文关键词，严格按照以下 JSON 数组的格式输出，不要带任何其他字符，以方便程序读取：
[KEYWORDS_JSON_START]
["关键词1", "关键词2", "关键词3", ...]
[KEYWORDS_JSON_END]
"""

# 第三步 Prompt：你的终极判定策略
PROMPT_STEP_3 = """
你是一位拥有10年实战经验的韩国 Coupang 跨境电商运营专家，精通韩语语义分析、VOC（用户之声）挖掘以及“精铺快速测品”的高 ROAS 广告策略。我们做的韩国电商coupang平台，但我是一个中国卖家，输出我能看懂的结果。关键词相关内容不要翻译英文，保持韩文，只要有对应的中文示意即可。

**核心任务：**
用户提供了“产品详情页长图”及“Naver关键词客观搜索量数据”。你需要基于产品特性和数据表现，输出精准广告分组、否定词表。所有关于关键词的分析不要含有LxU的品牌词。

以下是第二步抓取到的客观市场搜索量数据（格式为表格）：
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
   * 按分类制作三组关键词结果列表。保证准确的情况下尽量保证关键词数量。关键词后面不需要带出处的小标志。
* **总搜索量列：** 引用数据中的 total 总和，无数据则预估。

**模块二：否定关键词列表 (Negative Keywords)**
*用于广告后台屏蔽，防止无效烧钱。*
* **建议屏蔽的词：** [词1], [词2], [词3]...
* **屏蔽原因：** [简述，例如：材质不符、场景错误等]
"""

# ==========================================
# 3. 第二步核心：Naver API 抓取函数
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
    total_kws = len(main_keywords)
    
    for i, mk in enumerate(main_keywords, start=1):
        status_text.text(f"[{i}/{total_kws}] 正在抓取 Naver 数据: {mk}")
        progress_bar.progress(i / total_kws)
        
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
                    # 为了防止数据量过大撑爆 AI 上下文，每个主词最多只取前 15 个相关词
                    for item in data["keywordList"][:15]: 
                        pc = normalize_count(item.get("monthlyPcQcCnt", 0))
                        mob = normalize_count(item.get("monthlyMobileQcCnt", 0))
                        all_rows.append({
                            "主词": mk,
                            "拓展词": item.get("relKeyword", ""),
                            "Total搜索量": pc + mob,
                            "竞争度": item.get("compIdx", "-")
                        })
        except Exception as e:
            pass # 忽略错误，继续下一个
        time.sleep(1.2) # API 限流保护
        
    df = pd.DataFrame(all_rows)
    # 按搜索量排序并去重
    if not df.empty:
        df = df.drop_duplicates(subset=["拓展词"]).sort_values(by="Total搜索量", ascending=False)
    return df

# ==========================================
# 4. 主 UI 界面与流程控制
# ==========================================
st.title("⚡ LxU 自动化测品工厂")
st.info("三合一工作流：1. 视觉提炼 ➡️ 2. Naver 数据回测 ➡️ 3. AI 终极广告策略排兵布阵")

files = st.file_uploader("上传 PDF 详情页", type=["pdf", "png", "jpg"], accept_multiple_files=True)

if files and st.button("🚀 启动自动化流水线"):
    model = genai.GenerativeModel(model_name="gemini-2.5-flash") # 依然推荐 Flash 处理主流程
    
    for file in files:
        st.divider()
        st.header(f"📦 正在处理：{file.name}")
        
        # 保存临时文件
        temp_path = f"temp_{file.name}"
        with open(temp_path, "wb") as f:
            f.write(file.getbuffer())
        
        # ================= 步骤一 =================
        with st.status("🔍 第一步：大模型视觉提炼初筛词...", expanded=True) as s1:
            gen_file = genai.upload_file(path=temp_path)
            while gen_file.state.name == "PROCESSING":
                time.sleep(2)
                gen_file = genai.get_file(gen_file.name)
                
            res1 = model.generate_content([gen_file, PROMPT_STEP_1])
            
            # 智能提取 JSON 数组
            kw_list = []
            try:
                match = re.search(r"\[KEYWORDS_JSON_START\](.*?)\[KEYWORDS_JSON_END\]", res1.text, re.DOTALL)
                if match:
                    kw_list = json.loads(match.group(1).strip())
            except:
                st.warning("JSON 提取失败，启动备用正则抓取...")
                kw_list = re.findall(r'[ㄱ-ㅎㅏ-ㅣ가-힣]+', res1.text)[:20] # 备用提取韩文
                
            st.success(f"成功提取 {len(kw_list)} 个初筛词！")
            with st.expander("查看初筛报告"):
                st.write(res1.text)
            s1.update(label="✅ 第一步完成", state="complete", expanded=False)

        # ================= 步骤二 =================
        with st.status("📊 第二步：通过 Naver API 获取真实数据...", expanded=True) as s2:
            if not kw_list:
                st.error("未获取到关键词，跳过步骤。")
                continue
                
            pb = st.progress(0)
            status_txt = st.empty()
            df_market = fetch_naver_data(kw_list, pb, status_txt)
            
            st.dataframe(df_market.head(10)) # 只展示前 10 条
            s2.update(label="✅ 第二步完成", state="complete", expanded=False)

        # ================= 步骤三 =================
        with st.status("🧠 第三步：AI 大脑综合决策 (合并数据与图像)...", expanded=True) as s3:
            # 将 DF 转为紧凑的 CSV 格式喂给 AI
            market_csv_string = df_market.to_csv(index=False) 
            final_prompt = PROMPT_STEP_3.format(market_data=market_csv_string)
            
            # 双重输入：PDF 文件对象 + 带有搜索量数据的 Prompt
            res3 = model.generate_content([gen_file, final_prompt])
            st.markdown(res3.text)
            s3.update(label="✅ 第三步完成：终极策略已生成", state="complete", expanded=True)

        # 清理与导出
        os.remove(temp_path)
        genai.delete_file(gen_file.name) # 清理云端文件节省空间
        
        # 导出结果
        final_report = f"### 第一步：初筛词\n{', '.join(kw_list)}\n\n### 终极决策\n{res3.text}"
        st.download_button(
            label="📥 下载终极分析报告 (TXT)", 
            data=final_report, 
            file_name=f"LxU_Final_{file.name}.txt"
        )
