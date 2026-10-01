# X 视频采集与反向代理播放站

从 X (Twitter) 采集视频，自动整理数据，通过 Cloudflare Pages 反向代理
X 媒体 CDN，实现在线播放的完整方案。

---

## 目录

- [这是什么](#这是什么)
- [整体架构](#整体架构)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [采集工具 main.py](#采集工具-mainpy)
- [数据合并 merge_all.py](#数据合并-merge_allpy)
- [部署反向代理站](#部署反向代理站)
- [核心文件说明](#核心文件说明)
- [常见问题](#常见问题)
- [项目文件清单](#项目文件清单)
- [开源前准备](#开源前准备)
- [免责声明](#免责声明)
- [许可证](#许可证)
- [致谢](#致谢)

---

## 这是什么

本项目解决一个问题：X 上的视频链接经常无法直接播放（CORS、区域限制、
CDN 鉴权等）。整套流程分三步：

1. 采集：用 Playwright 驱动浏览器登录 X，抓取搜索、收藏夹、用户主页、
   单帖里的视频。
2. 整理：把所有 JSON 合并去重，只保留 title / cover / video_url。
3. 播放：把数据丢到 Cloudflare Pages，通过边缘函数反向代理媒体 CDN，
   前端直接在线播放。

---

## 整体架构

    +--------------------+     +------------------+     +--------------------+
    |  main.py           |     |  merge_all.py    |     |  Cloudflare Pages  |
    |  Playwright 爬虫   | --> |  JSON 合并去重   | --> |  反代 + 前端播放   |
    +--------------------+     +------------------+     +--------------------+
            |                          |                         |
       抓 X 视频链接              产出 all.json            代理 X 媒体 CDN

**为什么需要反向代理**

- X 的媒体 CDN 带鉴权，直接 video src 会被拦。
- Cloudflare 边缘函数转发请求时带上正确 Header，前端只看到自己的域名。
- 附带一份 cfall.json，把原始链接全部替换成你自己的反向代理域名。

---

## 目录结构

    反向代理/                          <-- 项目根目录
    |
    +-- functions/                     <-- 边缘函数目录
    |   +-- _middleware.js             <-- 全局中间件，生成 cfall.json
    |   +-- proxy/
    |       +-- [[path]].js            <-- 反向代理 X 媒体 CDN
    |
    +-- public/                        <-- 静态资源目录
    |   +-- all.json                   <-- 爬虫整理后的原始数据
    |   +-- index.html                 <-- 抖音风格前端
    |
    +-- _routes.json                   <-- 路由控制

配套的 Python 脚本，放在任意位置即可：

    main.py          爬虫
    merge_all.py     合并工具
    部署命令.txt     部署备忘
    结构图.txt       结构备忘

---

## 快速开始

### 0. 环境要求

- Python 3.9+
- Node.js 18+，用于 Wrangler
- Windows / macOS / Linux 均可
- 已安装 Edge 或 Chrome
- 一个 Cloudflare 账号

### 1. 安装 Python 依赖

    pip install playwright

不需要 playwright install，直接用系统自带的 Edge。

### 2. 采集数据

    python main.py

按提示选择模式 1 到 7。首次运行会弹出浏览器，手动登录 X 一次即可，
会话会保存在 ./x_profile。

### 3. 合并数据

    python merge_all.py ./output

产出的 all.json 复制到 public/ 目录。

### 4. 部署反向代理站

    npm install -g wrangler
    wrangler login
    cd 你的项目绝对路径
    wrangler pages deploy public --project-name=你的项目名字

---

## 采集工具 main.py

### 七种模式

| 模式 | 说明 |
|---|---|
| 1 | 搜索标签，按热度排序，自动收藏最火的视频帖 |
| 2 | 采集收藏夹内容，标题加封面加 m3u8 |
| 3 | 模式 1 加模式 2 连招 |
| 4 | 搜索关键词或名字，自动收藏最火的视频帖 |
| 5 | 模式 4 加模式 2 连招 |
| 6 | 采集某个用户所有带视频的帖子 |
| 7 | 采集单个帖子 |

### 可调参数

位于 main.py 顶部：

    HEADLESS       = False          是否无头模式
    BROWSER        = "msedge"       浏览器
    USER_DATA_DIR  = "./x_profile"  登录态保存目录
    OUTPUT_DIR     = "./output"     输出目录
    SCROLL_PAUSE   = 1500           滚动间隔，毫秒
    BOOKMARK_PAUSE = 2500           收藏间隔，毫秒

### 工作原理

- 监听 GraphQL 响应：搜索用 SearchTimeline，收藏夹用 Bookmark，
  单帖用 TweetDetail，用户主页则抓所有 /graphql/ 响应。
- 首屏兜底：读取 window.__INITIAL_STATE__，防止 X 把首屏数据内嵌在
  HTML 的 script 里而不走 GraphQL。
- 滚动策略：scrollTo 到最底，再补滚一屏触发下一批请求，连续 8 次
  无新响应才停。
- 视频抽取：递归查找本层、转推 retweeted_status_result、引推
  quoted_status_result，优先取 m3u8，否则取最高码率 mp4。

### 输出示例

    [
      {
        "title": "推文正文",
        "cover": "https://pbs.twimg.com/media/xxx.jpg",
        "video_url": "https://video.twimg.com/ext_tw_video/xxx.m3u8"
      }
    ]

---

## 数据合并 merge_all.py

### 作用

把目录下所有 JSON 递归遍历，抽成统一格式并去重。

### 用法

    python merge_all.py                扫当前目录
    python merge_all.py ./data         扫指定目录

### 输出格式

    [
      {
        "title": "推文正文",
        "cover": "https://pbs.twimg.com/...",
        "video_url": "https://video.twimg.com/....m3u8"
      }
    ]

### 去重规则

按 video_url 去重。

### 字段兼容

| 目标字段 | 兼容来源 |
|---|---|
| title | title / text / full_text |
| cover | cover / thumbnail / media_url |
| video_url | video_url / m3u8 / play_url / url |

### 注意事项

- 会自动跳过 all.json 自身，避免自己吃自己。
- 会跳过以点开头的隐藏文件。
- 单个文件解析失败只会跳过，不会中断整体流程。
- 标题里的换行和多余空白会被压平成一个空格。

---

## 部署反向代理站

### 部署命令

见 部署命令.txt：

    # 1. 装 Wrangler
    npm install -g wrangler

    # 2. 登录 Cloudflare
    wrangler login

    # 3. 进入项目路径
    cd 你的项目绝对路径

    # 4. 正式部署项目
    wrangler pages deploy public --project-name=你的项目名字

### 只用反向代理，不要前端

如果只想拿反向代理后的直链，删除 public/index.html 即可。
然后访问一次：

    https://你的域名/cfall.json

复制里面的内容直接用。

### 自定义域名

在 Cloudflare Pages 里绑定自定义域名后，_middleware.js 会自动适配，
无需改代码。

---

## 核心文件说明

### functions/_middleware.js

全局中间件，负责生成 cfall.json。

- 拦截请求，把所有原始 X 链接换成你当前的域名。
- 添加自定义域名后，访问域名会自动适配，链接会自适应更改。
- 访问一次 https://你的域名/cfall.json 就能拿到反代后的直链列表。

### functions/proxy/[[path]].js

反向代理 X 媒体 CDN。

- 把 /proxy/... 的请求转发给 X 媒体 CDN。
- 自动带上正确的 Header，绕过鉴权。
- 支持视频和图片资源。

### _routes.json

路由控制，示例：

    {
      "version": 1,
      "include": ["/proxy/*", "/cfall.json"],
      "exclude": []
    }

### public/index.html

抖音风格前端播放页。

- 从 cfall.json 或 all.json 读取数据。
- 全屏上下滑动切换视频。
- 直接调用反代域名播放。

---

## 常见问题

**Q: 为什么必须登录？**

X 的很多接口（搜索、收藏夹）对游客限制严格，登录后能拿到完整数据。

**Q: 采集到 0 条视频怎么办？**

模式 6 会在采不到时自动写 user_debug.json，把它发到 Issue 里即可。

**Q: 反向代理后视频 403？**

检查 [[path]].js 里转发的 Header 是否完整，尤其是 Referer 和
User-Agent。

**Q: 可以用自己的域名吗？**

可以。在 Cloudflare Pages 里绑定自定义域名后，_middleware.js 会自动
适配，无需改代码。

**Q: 数据会丢吗？**

main.py 每次运行都会覆盖同名输出文件，请及时改名或转移。
脚本结束时也会打印本次生成的所有文件路径提醒你。

**Q: 登录态存在哪里？**

存在 ./x_profile 目录里。这个目录包含你的 Cookie，绝对不要提交到
Git 仓库。

**Q: 支持哪些浏览器？**

默认用系统自带的 Edge，BROWSER = "msedge"。也可以改成 "chrome"。
不用 playwright install 装 Chromium。

---

## 项目文件清单

    反向代理/
    +-- functions/
    |   +-- _middleware.js
    |   +-- proxy/
    |       +-- [[path]].js
    +-- public/
    |   +-- all.json
    |   +-- index.html
    +-- _routes.json

    独立脚本：
    +-- main.py
    +-- merge_all.py
    +-- 部署命令.txt
    +-- 结构图.txt
    +-- README.md
    +-- LICENSE
    +-- .gitignore

---

## 开源前准备

### 1. 添加 .gitignore

在项目根目录创建 .gitignore：

    # Python
    __pycache__/
    *.py[cod]
    *$py.class
    *.so
    .Python
    build/
    dist/
    *.egg-info/
    .venv/
    venv/
    env/

    # Playwright 登录态，包含 Cookie，绝对不能提交
    x_profile/
    x_profile*/

    # 爬虫输出
    output/
    *.json.bak

    # Node
    node_modules/
    npm-debug.log*
    yarn-debug.log*
    yarn-error.log*

    # Cloudflare Wrangler
    .wrangler/
    .dev.vars
    .dev.vars.*

    # 编辑器
    .vscode/
    .idea/
    *.swp
    *.swo
    *~

    # 系统
    .DS_Store
    Thumbs.db
    desktop.ini

    # 日志
    *.log
    logs/

重点：x_profile/ 里有你的登录 Cookie，绝对不能提交。

### 2. 添加 LICENSE

在项目根目录创建 LICENSE，内容用 MIT：

    MIT License

    Copyright (c) 2025 [你的名字或用户名]

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

### 3. 清理敏感信息

开源前检查以下内容：

- 部署命令.txt 里的项目名、自定义域名，替换成 your-project-name、
  your-domain。
- all.json 里如果有真实数据，替换成示例数据或直接清空。
- _middleware.js 里如果硬编码了域名，改成读取环境变量或请求头。
- 检查所有 .js、.py、.txt 里有没有写死的个人路径，
  比如 C:\Users\win10\...

### 4. 提交到 GitHub

    git init
    git add .
    git commit -m "Initial commit"
    git branch -M main
    git remote add origin https://github.com/你的用户名/仓库名.git
    git push -u origin main

推送前用 git status 确认 x_profile/ 和 output/ 没有被加进去。

### 5. 建议添加的文件

- .gitignore
- LICENSE
- README.md
- requirements.txt
- CONTRIBUTING.md，可选
- .github/ISSUE_TEMPLATE/，可选

---

## 免责声明

- 本项目仅供学习与技术研究使用。
- 请遵守 X 的服务条款与当地法律法规。
- 请勿用于商业用途或大规模爬取。
- 采集到的内容版权归原作者所有，使用时请注明出处。
- 因使用本项目造成的任何后果，作者不承担责任。

---

## 许可证

MIT License，详见根目录 LICENSE 文件。

---

## 致谢

- Playwright：浏览器自动化
- Cloudflare Pages：静态托管加边缘函数
- Wrangler：部署 CLI

---

本项目与 X Corp. 无任何关联。
