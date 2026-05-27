# MediaFetch 媒体抓取

通用媒体链接解析器与下载器，支持抖音、B站、小红书、TikTok、YouTube、Twitter/X、微博、快手等平台。

粘贴分享文案或链接，自动解析并下载视频/图片到本地。

## 功能

- 解析分享文案中的短链，自动跳转获取真实链接
- 支持视频和图文（幻灯片）下载
- 自动去重缓存，相同链接不重复下载
- Web UI 界面，支持解析、文件库、历史、日志查看
- Lightbox 图片/视频预览，支持键盘导航和触摸滑动
- 移动端自适应布局

## 快速开始

### 环境要求

- Python 3.10+
- FFmpeg（视频转码需要，自行安装并加入 PATH，或将解压后的 `ffmpeg-master-latest-win64-gpl` 目录放在项目根目录下）

### 安装

```bash
pip install -r requirements.txt
```

### 配置

复制 `.env.example` 为 `.env`，按需修改：

```bash
cp .env.example .env
```

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `MF_PORT` | `9000` | 监听端口 |
| `MF_PREFIX` | 空 | 路径前缀，反向代理子路径部署时使用，如 `/download` |
| `MF_FFMPEG_PATH` | 自动发现 | FFmpeg 可执行文件路径或目录 |
| `MF_DOWNLOADS_DIR` | `./downloads` | 下载文件存储目录，支持绝对路径和相对路径 |
| `MF_API_KEY` | 每次启动随机生成 | API 访问密钥，控制台输出 |

### 启动

```bash
python server.py
```

服务启动后访问 http://localhost:9000 即可使用 Web UI。

## API

`/api/*` 接口需要 API Key 认证，支持三种传参方式：

| 方式 | 示例 |
|------|------|
| Header | `X-API-Key: your_key` |
| Query 参数 | `/api/parse?url=...&key=your_key` |
| JSON Body | `{"url": "...", "key": "your_key"}` |

### 接口列表

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/parse?url=` | 解析链接或分享文案 |
| POST | `/api/parse` | 同上，支持 JSON / 表单 / 纯文本 |
| GET | `/api/download/{path}` | 下载已保存的媒体文件 |

详细的参数和响应说明请访问 Web UI 内的「说明」页面。

## 技术栈

- **后端**: Python / FastAPI / uvicorn
- **HTTP 客户端**: httpx（异步）
- **视频解析**: yt-dlp
- **前端**: 原生 HTML + Tailwind CSS + Vanilla JS

## 项目结构

```
media-fetch/
├── server.py           # 后端服务
├── requirements.txt    # Python 依赖
├── .env.example        # 配置模板
├── static/
│   ├── index.html      # Web UI 页面结构
│   ├── style.css       # 自定义样式
│   └── app.js          # 前端逻辑
└── downloads/          # 下载文件存储目录
    └── {日期}/{平台}/
```

## 支持平台

| 平台 | 域名 |
|------|------|
| 抖音 | douyin.com / iesdouyin.com |
| B站 | bilibili.com / b23.tv |
| 小红书 | xiaohongshu.com / xhslink.com |
| TikTok | tiktok.com |
| YouTube | youtube.com / youtu.be |
| Twitter/X | twitter.com / x.com |
| 微博 | weibo.com |
| 快手 | kuaishou.com |

## 许可证

MIT
