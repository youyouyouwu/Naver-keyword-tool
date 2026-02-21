import csv
import time
import requests
import hashlib
import hmac
import base64
import pandas as pd
import glob
from pathlib import Path
import re

# =============== 这里填你的 API 信息 ==================
API_KEY = st.secrets["API_KEY"]
SECRET_KEY = st.secrets["SECRET_KEY"].encode("utf-8")
CUSTOMER_ID = st.secrets["CUSTOMER_ID"]
# =====================================================

API_URL = "https://api.searchad.naver.com/keywordstool"


def clean_for_api(keyword: str) -> str:
    """去掉空格，给 API 用"""
    return re.sub(r"\s+", "", keyword)


def make_signature(method: str, uri: str, timestamp: str) -> str:
    """按官方要求生成签名"""
    message = f"{timestamp}.{method}.{uri}".encode("utf-8")
    signature = hmac.new(SECRET_KEY, message, hashlib.sha256).digest()
    return base64.b64encode(signature).decode("utf-8")


def normalize_count(raw):
    """
    把 Naver 返回的 pc / mobile 转成整数，用于 total 计算：
    - 正常 int: 原样返回
    - 字符串 "< 10": 近似当 5（有一点量，但很小）
    - 其他情况: 尝试转 int，失败则当 0
    """
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("<"):
            return 5
        if s.startswith(">"):
            # 例如 "> 10" -> 10（很少见）
            num = s[1:].strip()
            return int(num) if num.isdigit() else 0
        # 纯数字字符串
        s = s.replace(",", "")
        if s.isdigit():
            return int(s)
    return 0


def get_related_keywords(main_keyword: str, retry: int = 3):
    """
    对一个主词调用一次 API，返回：
    - 主词本身（is_core = Y）
    - 所有 relKeyword（is_core = N）
    失败时返回一条 error 记录。
    """
    query_kw = clean_for_api(main_keyword)
    results = []

    for attempt in range(1, retry + 1):
        try:
            timestamp = str(int(time.time() * 1000))
            signature = make_signature("GET", "/keywordstool", timestamp)

            headers = {
                "X-Timestamp": timestamp,
                "X-API-KEY": API_KEY,
                "X-Customer": CUSTOMER_ID,
                "X-Signature": signature,
            }

            params = {
                "hintKeywords": query_kw,
                "showDetail": 1,
            }

            res = requests.get(API_URL, headers=headers, params=params)

            # 空响应，重试
            if not res.text or not res.text.strip():
                print(f"{main_keyword} 空响应，第 {attempt} 次重试")
                time.sleep(1.5)
                continue

            if res.status_code != 200:
                print(f"{main_keyword} HTTP {res.status_code}: {res.text}")
                time.sleep(1.5)
                continue

            data = res.json()

            if "keywordList" not in data or len(data["keywordList"]) == 0:
                # 主词没有任何数据
                results.append({
                    "main_keyword": main_keyword,
                    "rel_keyword": "",
                    "is_core": "Y",
                    "pc": 0,
                    "mobile": 0,
                    "total": 0,
                    "competition": "-",
                    "error": "No Data",
                })
                return results

            cleaned_main = clean_for_api(main_keyword)

            for item in data["keywordList"]:
                rel_kw = item.get("relKeyword", "")

                # pc / mobile 原样保留（可能是 int，也可能是 "< 10"）
                pc_raw = item.get("monthlyPcQcCnt", 0)
                mobile_raw = item.get("monthlyMobileQcCnt", 0)

                # total 使用“合算后”的值
                pc_val = normalize_count(pc_raw)
                mobile_val = normalize_count(mobile_raw)
                total = pc_val + mobile_val

                comp = item.get("compIdx", "-")

                # 去掉空格后的字符串比较，判断是不是主词本身
                is_core = "Y" if clean_for_api(rel_kw) == cleaned_main else "N"

                results.append({
                    "main_keyword": main_keyword,
                    "rel_keyword": rel_kw,
                    "is_core": is_core,
                    "pc": pc_raw,          # 原始值
                    "mobile": mobile_raw,  # 原始值
                    "total": total,        # 合算结果
                    "competition": comp,
                    "error": "",
                })

            return results

        except Exception as e:
            print(f"{main_keyword} 出错：{e}，第 {attempt} 次重试")
            time.sleep(1.5)

    # 多次重试失败，写一条失败记录
    results.append({
        "main_keyword": main_keyword,
        "rel_keyword": "",
        "is_core": "Y",
        "pc": 0,
        "mobile": 0,
        "total": 0,
        "competition": "-",
        "error": "Failed after retries",
    })
    return results


def find_input_file():
    """
    自动找一个输入文件：
    - 优先使用当前目录下的第一个 .xlsx
    - 如果没有 .xlsx，再找第一个 .csv
    """
    xlsx_files = glob.glob("*.xlsx")
    if xlsx_files:
        return xlsx_files[0], "xlsx"

    csv_files = glob.glob("*.csv")
    if csv_files:
        return csv_files[0], "csv"

    raise FileNotFoundError("❌ 当前目录下没有找到 xlsx 或 csv 文件，请先上传。")


# ============= 主流程 =============

input_file, file_type = find_input_file()
print("📌 使用的文件：", input_file, "| 类型：", file_type)

# 读取主词列表（默认第一列）
main_keywords = []

if file_type == "xlsx":
    df_kw = pd.read_excel(input_file)
    # 默认第一列是关键词
    first_col = df_kw.columns[0]
    for v in df_kw[first_col].astype(str):
        v = v.strip()
        if v:
            main_keywords.append(v)
else:
    with open(input_file, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)  # 跳过表头
        for row in reader:
            if not row:
                continue
            kw = str(row[0]).strip()
            if kw:
                main_keywords.append(kw)

print(f"📌 主词数量：{len(main_keywords)}")

all_rows = []
for i, mk in enumerate(main_keywords, start=1):
    print(f"[{i}/{len(main_keywords)}] 处理主词：{mk}")
    rows = get_related_keywords(mk)
    all_rows.extend(rows)
    time.sleep(1.0)  # 稍微慢一点，避免触发限流

# 生成 DataFrame
df = pd.DataFrame(
    all_rows,
    columns=[
        "main_keyword",
        "rel_keyword",
        "is_core",
        "pc",
        "mobile",
        "total",
        "competition",
        "error",
    ],
)

# ---------- 清洗与去重 ----------

# 1）找到哪些 main_keyword 至少有一条成功记录（error == ""）
has_success = df.groupby("main_keyword")["error"].apply(lambda s: (s == "").any())
ok_keywords = has_success[has_success].index

# 2）这些有成功数据的主词：只保留成功行
df_ok = df[(df["main_keyword"].isin(ok_keywords)) & (df["error"] == "")]

# 3）完全失败的主词：保留它们的失败行
df_fail_only = df[~df["main_keyword"].isin(ok_keywords)]

# 4）合并，并按 main_keyword + rel_keyword + is_core 去重
df_clean = pd.concat([df_ok, df_fail_only], ignore_index=True)
df_clean = df_clean.drop_duplicates(
    subset=["main_keyword", "rel_keyword", "is_core"],
    keep="first",
)

output_name = "naver_keyword_with_related.xlsx"
df_clean.to_excel(output_name, index=False)

print("🎉 完成！已生成（total 为 pc+mobile 合算）：", output_name)
