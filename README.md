# Picora 模块仓库

[Picora](https://github.com/Alnitak44/Picora) 的在线插件目录。客户端读取自动生成的 [index.json](index.json)，从插件作者的 GitHub Release 下载 ZIP，并校验插件身份、版本、大小和 SHA-256。

## 已收录插件

<!-- catalog:start -->
| 插件 | 版本 | 说明 |
| --- | --- | --- |
| [ImgLoc 图床](https://github.com/Alnitak44/picora-plugins/tree/main/plugins/imgloc) | 1.1.0 | ImgLoc 图片上传，自动获取并刷新临时上传凭证。 |
| [Telegraph-Image](https://github.com/Alnitak44/Picora/tree/main/plugins/telegraph-image) | 1.1.1 | 连接 cf-pages/Telegraph-Image 自建图床 |
| [ImgBB 图床](https://github.com/ruzmariN/picora-plugin-imgbb) | 1.0.0 | 使用 ImgBB API Key 上传图片并获取直链。 |
| [聚合图床 (Superbed)](https://github.com/ruzmariN/picora-plugin-superbed) | 1.0.0 | 使用聚合图床 API Key 上传图片并获取直链。 |
<!-- catalog:end -->

## 投稿与更新

详细步骤见 [贡献指南](CONTRIBUTING.md)。

1. 按 [Picora 插件协议](https://github.com/Alnitak44/Picora/blob/main/docs/PLUGINS.md)制作并测试 ZIP，在自己的公开 GitHub 仓库创建 Release，上传 ZIP 附件。
2. Fork 本仓库，在 `registrations/<插件 ID>.json` 新增一份登记文件，然后提交 PR。[通用登记示例](examples/io.github.example.picora.demo.json)可作为起点。
3. CI 从 Release 读取 ZIP，检查 ID、运行时、请求权限和包结构，并自动生成 `index.json` 与上面的表格。维护者审核首发插件及其请求权限后合并。
4. 后续发布新版本的 ZIP 即可。仓库计划每小时检查 Release；若请求权限发生变化，需要通过 PR 更新登记文件并接受审核。

投稿时无需手填下载 URL、ZIP 大小或 SHA-256。这些值仍保留在机器生成的 `index.json` 中，供客户端安全下载。插件源码与许可证归作者维护；目录使用 [MIT](LICENSE) 协议。
