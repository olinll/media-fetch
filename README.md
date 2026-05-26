# Media Fetch

通用媒体链接解析器与下载器，支持抖音、B站、小红书、TikTok、YouTube、Twitter/X、微博、快手等平台。

粘贴分享文案或链接，自动解析并下载视频/图片到本地。

## 功能

- 解析分享文案中的短链，自动跳转获取真实链接
- 支持视频和图文（幻灯片）下载
- 自动去重缓存，相同链接不重复下载
- Web UI 界面，支持解析、文件库、历史、日志查看
- Lightbox 图片/视频预览，支持键盘导航和触摸滑动
- iOS 捷径集成，手机端一键解析
- 移动端自适应布局

## 快速开始

### 环境要求

- Python 3.10+
- FFmpeg（视频转码需要，Windows 下项目已内置）

### 安装

```bash
pip install -r requirements.txt
```

### 启动

```bash
python server.py
```

或 Windows 下双击 `start.bat`。

服务启动后访问 http://localhost:9000 即可使用 Web UI。

### 防火墙（局域网访问）

Windows 管理员 PowerShell 执行：

```powershell
netsh advfirewall firewall add rule name="Media Fetch" dir=in action=allow protocol=TCP localport=9000
```

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
├── start.bat           # Windows 启动脚本
├── API.md              # API 接口文档
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
