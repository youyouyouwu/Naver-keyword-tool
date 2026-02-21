with st.status("🔍 正在执行第一步：Gemini 识图提取...", expanded=True) as s1:
            gen_file = genai.upload_file(path=temp_path)
            while gen_file.state.name == "PROCESSING":
                time.sleep(2)
                gen_file = genai.get_file(gen_file.name)
                
            res1 = model.generate_content([gen_file, PROMPT_STEP_1])
            st.markdown("**大模型原始输出结果：**")
            with st.expander("点击查看 Gemini 输出全文 (用来核对 AI 有没有偷懒)"):
                st.write(res1.text)
                
            # --- 🚀 核心升级：防弹级关键词提取逻辑 ---
            # 1. 忽略大小写、兼容各种奇怪换行的锚点寻找
            match = re.search(r"\[LXU_KEYWORDS_START\](.*?)\[LXU_KEYWORDS_END\]", res1.text, re.DOTALL | re.IGNORECASE)
            
            kw_list = []
            if match:
                raw_block = match.group(1)
                # 2. 暴力提取：不管它是逗号、换行还是带了数字，直接把所有“纯韩文词组”抓出来！
                # [가-힣]+ 代表只匹配韩文，完美过滤掉中英文、数字和标点
                extracted_words = re.findall(r'[가-힣]+', raw_block)
                
                # 3. 去重（保留原本的顺序）
                kw_list = list(dict.fromkeys(extracted_words))
            else:
                st.warning("⚠️ 未检测到标准锚点，启动备用方案：强制从全文末尾提取韩文...")
                # 备用方案：如果 AI 连锚点都忘了写，直接抓文章最后 500 个字符里的所有韩文
                tail_text = res1.text[-500:]
                extracted_words = re.findall(r'[가-힣]+', tail_text)
                # 去重后最多取 25 个词去测
                kw_list = list(dict.fromkeys(extracted_words))[:25] 
                
            if kw_list:
                s1.update(label=f"✅ 第一步完成！成功暴力截获 {len(kw_list)} 个纯韩文关键词", state="complete")
                st.success(f"Python 成功拿到的最终列表（即将喂给 Naver）：{kw_list}")
            else:
                s1.update(label="❌ 第一步提取彻底失败", state="error")
                st.error("大模型的输出中没有任何有效的韩文字符，请检查图片是否清晰。")
