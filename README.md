# X平台内容运营辅助工具 (X28)

这是一个专为个人内容运营者打造的本地桌面小工具，旨在帮助您高效监控 X (Twitter) 平台的目标账号，挑选优质推文，并通过 AI (如最新的 **Gemini 3.5 Flash 免费层**) 一键生成极具吸引力的回复（Reply）、转推评论（Quote Tweet）及系列推文（Thread），从而轻量、半自动化地运营您的个人 X 账号。

---

## 🌟 核心功能

1. **监控账号管理**：本地持久化存储目标账号列表（右键或点击按钮即可添加/删除，数据存储在 `data/accounts.json`）。
2. **免登录推文抓取**：
   - 优先使用官方 X API v2（若配置了 Token）。
   - **自动降级方案**：在未配置 Token 或 API 欠费/受限时，自动以多实例轮询方式通过 **Nitter RSS 通道** 抓取目标账号最新 20 条推文。
3. **推文高亮选择**：点击列表中的任何一条推文，即可高亮选中并预览，底部自动激活 AI 生成面板。
4. **多模型免费/低成本生成**：
   - **默认支持 Gemini 3.5 Flash**（在 Google AI Studio 申请的 API Key 提供非常慷慨的免费调用额度）。
   - 兼容 OpenAI (如 `gpt-4o-mini`) 与 Anthropic Claude。
   - 直接使用标准 `requests` 库调用，无需安装庞大的官方 SDK。
5. **中英双语生成切换**：一键切换生成的目标语言（中文/英文）。
6. **一键复制分发**：生成文案支持在软件中直接编辑，并一键复制到剪贴板，方便在浏览器中快速粘贴分发。

---

## 📂 项目结构

```text
e:\Digital Nomads\X28\
├── data/
│   └── accounts.json       # 本地保存的监控账号数据 (首次启动自动创建)
├── .env                    # 本地运行配置文件 (需从 .env.example 复制并填写)
├── .env.example            # 配置文件模版
├── requirements.txt        # 依赖列表
├── README.md               # 项目说明文档
└── main.py                 # 主程序入口 (GUI界面与数据逻辑)
```

---

## 🚀 安装与运行步骤

### 1. 安装 Python 环境
确保您的 Windows 系统上已安装 Python 3.8 或以上版本。

### 2. 克隆/解压项目并安装依赖
在项目根目录下打开终端 (PowerShell 或 Cmd)，执行以下命令安装依赖：
```bash
pip install -r requirements.txt
```

### 3. 配置环境变量
1. 将项目根目录下的 `.env.example` 文件复制并重命名为 `.env`。
2. 打开 `.env`，填入您的 API 密钥。

#### 💡 如何获取免费的 Gemini API Key：
1. 访问 [Google AI Studio](https://aistudio.google.com/)。
2. 使用您的 Google 账号登录。
3. 点击 **"Get API key"** 按钮生成您的 Key。
4. 将生成的 Key 粘贴到 `.env` 的 `GEMINI_API_KEY` 一栏。
5. 保持 `LLM_PROVIDER=gemini` 且 `GEMINI_MODEL=gemini-3.5-flash`，即可使用官方免费额度的 Gemini 进行文本生成。

---

## 💻 启动软件

在项目目录下执行：
```bash
python main.py
```
运行后，软件将默认以**深色现代主题**启动。

---

## 📦 打包为单文件 `.exe`

如果您希望将软件打包为独立的可执行文件，无需 Python 环境即可在 Windows 上直接运行，可以按照以下步骤操作：

1. 安装 `pyinstaller`：
   ```bash
   pip install pyinstaller
   ```
2. 执行打包命令：
   ```bash
   pyinstaller --noconfirm --onedir --windowed --add-data "data;data" main.py
   ```
   *提示：如果需要生成单个 exe 文件，可以使用以下命令：*
   ```bash
   pyinstaller --noconfirm --onefile --windowed main.py
   ```
3. 打包完成后，生成的 `.exe` 文件将存放在项目根目录下的 `dist/` 文件夹中。请注意，运行该 `.exe` 前，其同级目录下仍需留存有配置好 API 密钥的 `.env` 文件。

---

## 🛠️ 常见问题排查 (FAQ)

- **Q1: 为什么提示推文获取失败，提示所有 Nitter 实例均不可用？**
  - **A**: 公共 Nitter 实例经常由于 X 官方的安全限制产生短时间屏蔽。您可以尝试在 `.env` 文件的 `NITTER_INSTANCES` 一行中添加或替换其他可用的 Nitter 公共实例，例如可以在 [Nitter Wiki](https://github.com/zedeus/nitter/wiki/Instances) 上查找当前存活的公共实例并填入配置文件中。
  - 另外，使用 Nitter 抓取需要您的本地网络能够正常访问海外网络。
- **Q2: AI 文本框生成显示连接超时？**
  - **A**: 调用 Google Gemini 或 OpenAI 等 API 需要您的网络畅通（如果在国内可能需要配置代理或使用中转 API）。如果您使用的是中转 API，可以在 `.env` 中填写对应的 `OPENAI_BASE_URL` 并使用 OpenAI 模式进行适配。
