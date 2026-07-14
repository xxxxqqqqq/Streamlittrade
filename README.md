```text
本项目为简单的量化策略回测网站
项目启动命令：streamlit run app.py 
app.py
├── 导入（新增 openai, os, re, dotenv）
├── 加载 .env，获取 API Key
├── 数据获取函数
├── 内置策略函数
├── DeepSeek 相关
│   ├── SYSTEM_PROMPT
│   ├── call_deepseek()
│   ├── extract_code()
│   └── validate_strategy_code()
├── 回测引擎
├── 可视化
├── Streamlit 界面
│   ├── st.set_page_config
│   ├── 初始化 session_state（消息、代码）
│   ├── 侧边栏
│   │   ├── 策略选择（增加 AI 选项）
│   │   ├── 策略参数（根据类型显示）
│   │   │   ├── 右侧 / V型：显示滑块
│   │   │   ├── AI 生成策略：显示聊天界面 + 代码编辑器
│   │   │   └── 自定义：显示代码编辑器
│   │   └── 交易参数
│   ├── 主界面
│   │   ├── run_btn 事件处理
│   │   │   ├── 获取数据
│   │   │   ├── 生成信号（分策略类型）
│   │   │   ├── 回测
│   │   │   └── 显示结果
│   │   └── 结果展示（指标、图表、交易明细）
└──
```