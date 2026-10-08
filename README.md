# Picora 模块仓库

[Picora](https://github.com/Alnitak44/Picora) 的在线插件目录。客户端读取 [index.json](index.json)，下载 Releases 中的 ZIP，并核对插件 ID、版本、大小和 SHA-256。

## 插件

| 插件 | 版本 | 说明 |
| --- | --- | --- |
| [Telegraph-Image](https://github.com/Alnitak44/Picora/tree/main/plugins/telegraph-image) | 1.1.1 | 首个插件及开发示例，连接自建 Telegraph-Image 图床 |

[下载插件](https://github.com/Alnitak44/picora-plugins/releases/tag/telegraph-image-v1.1.1) · [使用教程](https://github.com/Alnitak44/Picora/blob/main/plugins/telegraph-image/readme.md)

## 收录与更新

按 [插件协议](https://github.com/Alnitak44/Picora/blob/main/docs/PLUGINS.md) 制作 ZIP，发布到作者仓库的 GitHub Release，再提交修改 index.json 的 PR。

条目格式见 [模块目录协议](https://github.com/Alnitak44/Picora/blob/main/docs/PLUGIN_MARKETPLACE.md)。更新保持插件 ID 稳定，使用新的 SemVer 版本、下载地址和摘要；不要覆盖已发布版本的附件。

目录使用 [MIT](LICENSE) 协议。插件保留作者自己的版权与许可证。
