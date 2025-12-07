# Naver Keyword Tool

这个项目是一个用于 **批量查询 Naver 搜索广告关键词数据** 的小工具。

目前目标功能：

- 读取一个 Excel / CSV 文件（第一列为主关键词）
- 调用 Naver Searchad API：
  - 获取主关键词的 PC / Mobile 搜索量
  - 获取主关键词的关联关键词（relKeyword）
  - 统计合计搜索量（pc + mobile）
  - 获取官方竞争强度（compIdx）
- 把所有结果导出为 Excel 文件，方便在本地继续做筛选、分析、建词矩阵等工作

## 技术栈

- Python 3
- Flask / Streamlit（后续会选择一种作为 Web 前端）
- Pandas
- Requests
- Naver Searchad API

## 使用说明（规划中）

后续会在这里补充详细使用方法，包括：

- 如何准备关键词 Excel 表
- 如何配置 Naver API 的 KEY / SECRET / CUSTOMER_ID
- 如何本地运行项目
- 如何部署到线上（例如 Render / Streamlit Cloud）

## 作者

- GitHub: [youyouyouwu](https://github.com/youyouyouwu)




