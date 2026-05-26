# API 接口文档

服务监听 `0.0.0.0:9000`，所有接口均以此为基础路径。

---

## 1. 解析链接 `GET /parse`

从分享文案或链接中提取 URL，解析并下载媒体文件。重复链接会直接返回缓存结果。

**参数**

| 参数 | 位置 | 必填 | 说明 |
|------|------|------|------|
| `url` | query | 是 | 链接地址，或包含链接的分享文案 |

**请求示例**

```
GET /parse?url=2.05 复制打开抖音，看看【知了知了的图文作品】流萤AI图... https://v.douyin.com/LHUsGRLYwLg/
```

**响应示例**

```json
{
  "success": true,
  "platform": "抖音",
  "title": "流萤AI图。9比16的图是要比16比9图好抽一些 ...",
  "author": "知了知了",
  "type": "slides",
  "duration": 0,
  "original_url": "https://v.douyin.com/LHUsGRLYwLg/",
  "resolved_url": "https://www.douyin.com/note/7521023890996514083",
  "files": [
    {
      "type": "image",
      "filename": "1748234567_a1b2c3.jpg",
      "relative_path": "20260526/抖音/1748234567_a1b2c3.jpg",
      "url": "/download/20260526/抖音/1748234567_a1b2c3.jpg"
    }
  ]
}
```

缓存命中时响应会多一个字段：

```json
{
  "cached": true,
  "success": true,
  ...
}
```

---

## 2. 解析链接 `POST /parse`

与 GET 相同，适合 iOS 捷径用 POST JSON 方式调用。

**请求体**

```json
{
  "url": "2.05 复制打开抖音，看看【...】 https://v.douyin.com/LHUsGRLYwLg/"
}
```

或用 `text` 字段：

```json
{
  "text": "2.05 复制打开抖音，看看【...】 https://v.douyin.com/LHUsGRLYwLg/"
}
```

---

## 3. 下载文件 `GET /download/{path}`

下载已解析并保存到服务器的媒体文件，支持子目录路径。

```
GET /download/20260526/抖音/1748234567_a1b2c3.mp4
```

返回对应文件，Content-Type 根据扩展名自动判断。

---

## 4. 文件列表 `GET /files`

列出 downloads 目录中所有已下载文件。

```json
{
  "files": [
    {
      "filename": "1748234567_a1b2c3.mp4",
      "relative_path": "20260526/抖音/1748234567_a1b2c3.mp4",
      "size": 5242880,
      "url": "/download/20260526/抖音/1748234567_a1b2c3.mp4"
    }
  ]
}
```

---

## 5. 运行日志 `GET /api/logs`

获取服务运行日志。

**参数**

| 参数 | 位置 | 必填 | 说明 |
|------|------|------|------|
| `limit` | query | 否 | 返回条数，默认 200 |

```json
{
  "logs": [
    {
      "time": "2026-05-27 07:00:00",
      "level": "INFO",
      "message": "解析完成: 抖音"
    }
  ]
}
```

---

## 6. 统计信息 `GET /api/stats`

返回文件总数等统计信息。

```json
{
  "total": 12,
  "message": "文件永久保留，不提供删除接口"
}
```

---

## 7. 缓存记录 `GET /api/cache`

返回所有缓存的解析记录。

```json
{
  "entries": [
    {
      "platform": "抖音",
      "title": "流萤AI图",
      "author": "知了知了",
      "type": "slides",
      "original_url": "https://v.douyin.com/xxx/",
      "resolved_url": "https://www.douyin.com/note/xxx",
      "cached": true,
      "files": [...]
    }
  ]
}
```

---

## 文件存储结构

```
downloads/
├── 20260526/
│   ├── 抖音/
│   │   ├── 1748234567_a1b2c3.mp4
│   │   └── 1748234890_d4e5f6.jpg
│   └── B站/
│       └── 1748235000_f7g8h9.mp4
└── 20260527/
    └── 抖音/
        └── 1748321000_l3m4n5.mp4
```

路径格式: `downloads/{日期}/{平台}/{时间戳_随机6位}.{扩展名}`

---

## 去重缓存

- 缓存文件: `cache.json`（项目根目录）
- 以 `resolved_url` 为 key，相同链接直接返回缓存结果
- 缓存会校验文件是否还存在，文件丢失则自动重新下载
