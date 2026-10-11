# 贡献 Picora 插件

## 首次收录

1. 按 [插件协议](https://github.com/Alnitak44/Picora/blob/main/docs/PLUGINS.md)制作插件，在 Picora 中使用本地 ZIP 测试。
2. 将源码与说明放在自己控制的公开 GitHub 仓库，在该仓库的 Release 中上传 `.picora-plugin.zip` 附件。ZIP 根目录需包含 `plugin.json`、入口 JSON、`readme.md` 和所引用的资源。
3. Fork 本仓库，复制 [登记示例](examples/io.github.ruzmarin.picora.imgbb.json)到 `registrations/<插件 ID>.json`，修改以下字段后提交 PR：
   - `id`：与 ZIP 中的 `plugin.json` 完全相同。新插件使用 `io.github.<你的 GitHub 用户名小写>.<插件名>`。
   - `releaseRepository`：`用户名/仓库名`。ZIP 元信息中的 `repository` 应指向这个仓库。
   - `minAppVersion`：插件所需的 Picora 最低版本；`http-v2` 至少为 `1.0.1`。
   - `approvedPermissions`：与 ZIP 内入口 JSON 的 `permissions` 对应。网络目标会在首次收录时由维护者审核。
4. CI 读取该仓库的公开 Release，验证插件 ZIP 并预览生成的目录。维护者审核后合并，自动更新客户端读取的 `index.json`。

投稿者无需填写 Release 下载地址、ZIP 大小、SHA-256，也无需把 ZIP 或插件源码复制到本目录仓库。已有的内置示例保留为历史兼容项。

## 更新

在作者仓库发布带有新 ZIP 的 GitHub Release，插件 ID 保持不变，版本按 SemVer 增加。目录计划每小时检查一次；通过验证后自动更新。不要修改已发布版本的附件。

若新版本增加或改变网络目标、不安全 HTTP 或云端删除权限，自动更新会停止。请先对登记文件中的 `approvedPermissions` 提交 PR，说明变化并等待审核。Picora 用户安装更新时仍会看到插件的实际权限。
