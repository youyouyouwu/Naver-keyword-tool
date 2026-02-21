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
# 1. 页面与 API 密钥配置 
# ==========================================
st.set_page_config(page_title="LxU 连通性测试", layout="wide")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")
NAVER_API_KEY = st.secrets.get("API_KEY")
NAVER_SECRET_KEY = st.secrets.get("SECRET_KEY")
NAVER_CUSTOMER_ID = st.secrets.get("CUSTOMER_ID")

if not all([GEMINI_API_KEY, NAVER_API_KEY, NAVER_SECRET_KEY, NAVER_CUSTOMER_ID]):
    st.error("⚠️ 缺少密钥，请检查 .streamlit/secrets.toml 文件")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)
SECRET_KEY_BYTES = NAVER_SECRET_KEY.encode("utf-8")
NAVER_API_URL = "https://api.searchad.naver.com/keywordstool"

# ==========================================
# 2. 改造后的第一步 Prompt (加入精准锚点)
# ==========================================
PROMPT_STEP_1 = """
你是一个精通韩国 Coupang 运营的 SEO 专家。请分析我提供的产品详情页，完成以下任务：

第一，找出20个产品关键词（不包含品牌词），保留竖版序号排列外加策略解释的版本，含翻译文。
第二，找精准长尾词做付费推广，分为：广告组一【核心出单词】、广告组二【精准长尾关键词】、广告组三【长尾捡漏组广告词】。
第三，生成一个高点击率标题方案。
第四，提供产品韩语名称用于内部管理。
第五，撰写5条商品好评。
第六，将上述三个广告组的所有关键词进行去重汇总，单列纵向列表输出。
第七，AI 主图生成建议。

【程序读取专属指令 - 极度重要】：
为了方便我的系统自动抓取，请务必将**第六部分**的最终去重汇总关键词，放在以下两个标记之间输出！每行只写一个纯韩文关键词，不要带序号，不要带标点，不要带中文！
[LXU_KEYWORDS_START]
(在这里填入纯韩文关键词)
[LXU_KEYWORDS_END]
"""

# ==========================================
# 3. Naver API 数据查询函数 (保持不变)
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

def fetch_naver_data(main_keywords):
    all_rows = []
    for mk in main_keywords:
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
                    # 只取主词本身的数据，以及前3个拓展词进行测试，避免数据太长
                    for item in data["keywordList"][:4]: 
                        pc = normalize_count(item.get("monthlyPcQcCnt", 0))
                        mob = normalize_count(item.get("monthlyMobileQcCnt", 0))
                        all_rows.append({
                            "提取的主词": mk,
                            "Naver关联词": item.get("relKeyword", ""),
                            "总搜索量(PC+移动)": pc + mob,
                            "竞争强度": item.get("compIdx", "-")
                        })
        except Exception as e:
            pass
        time.sleep(1) # API 保护
    
    df = pd.DataFrame(all_rows)
    if not df.empty:
        df = df.drop_duplicates(subset=["Naver关联词"]).sort_values(by="总搜索量(PC+移动)", ascending=False)
    return df

# ==========================================
# 4. 运行界面与衔接逻辑测试
# ==========================================
st.title("🔧 第一步与第二步：衔接测试")

file = st.file_uploader("上传 PDF 详情页", type=["pdf", "png", "jpg"])

if file and st.button("🚀 开始测试一二步连接"):
    model = genai.GenerativeModel(model_name="gemini-2.5-flash")
    
    temp_path = f"temp_{file.name}"
    with open(temp_path, "wb") as f:
        f.write(file.getbuffer())
        
    with st.status("🔍 正在执行第一步：Gemini 识图提取...", expanded=True) as s1:
        gen_file = genai.upload_file(path=temp_path)
        while gen_file.state.name == "PROCESSING":
            time.sleep(2)
            gen_file = genai.get_file(gen_file.name)
            
        res1 = model.generate_content([gen_file, PROMPT_STEP_1])
        st.markdown("**大模型原始输出结果：**")
        with st.expander("点击查看 Gemini 输出全文"):
            st.write(res1.text)
            
        # 核心改进：精准正则表达式抓取锚点内的纯词汇
        match = re.search(r"\[LXU_KEYWORDS_START\](.*?)\[LXU_KEYWORDS_END\]", res1.text, re.DOTALL)
        if match:
            raw_text = match.group(1).strip()
            # 按换行符分割，并清除可能附带的数字序号、空格和中文字符
            kw_list = [re.sub(r'[^ㄱ-ㅎㅏ-ㅣ가-힣]', '', kw) for kw in raw_text.split('\n')]
            kw_list = [kw for kw in kw_list if kw] # 剔除空字符串
        else:
            kw_list = []
            
        s1.update(label=f"✅ 第一步完成！成功截获 {len(kw_list)} 个关键词", state="complete")
        st.success(f"Python 成功拿到的列表：{kw_list}")

    if kw_list:
        with st.status("📊 正在执行第二步：请求 Naver API 查数据...", expanded=True) as s2:
            df_market = fetch_naver_data(kw_list)
            if not df_market.empty:
                st.dataframe(df_market)
                s2.update(label="✅ 第二步完成！数据已生成表单", state="complete")
            else:
                st.error("❌ Naver API 未返回有效数据，可能是关键词格式错误或网络问题。")
    else:
        st.error("❌ 衔接失败！Python 没有找到 [LXU_KEYWORDS_START] 锚点，无法执行第二步。")
        
    os.remove(temp_path)
