# Picora 模块仓库

[Picora](https://github.com/Alnitak44/Picora) 的在线插件目录。客户端读取 [index.json](index.json)，下载 GitHub Releases 中的 ZIP，核对 ID、版本、大小和 SHA-256。

## 插件

| 插件 | 版本 | 说明 |
| --- | --- | --- |
| [Telegraph-Image](https://github.com/Alnitak44/Picora/tree/main/plugins/telegraph-image) | 1.1.1 | 开发示例，连接自建 Telegraph-Image 图床 |
| [ImgLoc](plugins/imgloc) | 1.1.0 | 自动获取临时凭证，http-v2 |

[Telegraph-Image 下载](https://github.com/Alnitak44/picora-plugins/releases/tag/telegraph-image-v1.1.1) · [ImgLoc 下载](https://github.com/Alnitak44/picora-plugins/releases/tag/imgloc-v1.1.0)

## 收录与更新

按 [插件协议](https://github.com/Alnitak44/Picora/blob/main/docs/PLUGINS.md) 制作 ZIP，在作者仓库发布 GitHub Release，再提交 index.json 条目的 PR。

保持 ID 稳定，使用新的 SemVer 版本、下载地址和摘要，不覆盖已发布版本的附件。合并前审核请求目标、凭证使用与删除语义。

目录使用 [MIT](LICENSE) 协议。插件保留作者自己的版权与许可证。
