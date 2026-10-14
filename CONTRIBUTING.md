# 贡献 Picora 插件

## 首次收录

1. 按 [插件协议](https://github.com/Alnitak44/Picora/blob/main/docs/PLUGINS.md)制作插件，在 Picora 中使用本地 ZIP 测试。
2. 将源码与说明放在自己控制的公开 GitHub 仓库，在该仓库的 Release 中上传 `.picora-plugin.zip` 附件。ZIP 根目录需包含 `plugin.json`、入口 JSON、`readme.md` 和所引用的资源。
3. Fork 本仓库，复制 [登记示例](examples/io.github.example.picora.demo.json)到 `registrations/<插件 ID>.json`，修改以下字段后提交 PR：
   - `id`：与 ZIP 中的 `plugin.json` 完全相同。新插件使用 `io.github.<你的 GitHub 用户名小写>.<插件名>`。
   - `releaseRepository`：`用户名/仓库名`。ZIP 元信息中的 `repository` 应指向这个仓库。
   - `minAppVersion`：插件所需的 Picora 最低版本；`http-v2` 至少为 `1.0.1`。
   - `approvedPermissions`：与 ZIP 内入口 JSON 的 `permissions` 对应。网络目标会在首次收录时由维护者审核。
4. CI 读取该仓库的公开 Release，验证插件 ZIP 并预览生成的目录。维护者审核后合并，自动更新客户端读取的 `index.json`。

投稿者无需填写 Release 下载地址、ZIP 大小、SHA-256，也无需把 ZIP 或插件源码复制到本目录仓库。所有插件（包括开发示例）在作者自己的独立仓库发布，目录仓库不托管插件 Release，不提供历史豁免。

### 检查失败时

在 PR 的 **Checks → Build plugin catalog → Validate proposed catalog** 查看错误。Action 会标出实际值和期望值；修正后提交到同一个 PR 分支即可重跑。已合并后的自动更新错误则在 **Actions → Build plugin catalog → Generate catalog** 查看。

目录会兼容登记文件名中仅有大小写差异，以及 Release 附件的常见后缀笔误（`.picora-plugin.zip.zip`、`.picora.plugin.zip`），并显示警告。仍建议使用标准文件名 `<插件 ID>.json` 和以 `.picora-plugin.zip` 结尾的 ZIP。ZIP 中缺少 `repository` 时，目录会使用已审核的 `releaseRepository` 生成作者仓库链接。

插件 ID、实际网络权限和已审核权限、明确填写的仓库地址仍须一致；这些涉及身份或权限，Action 不会猜测修改。ZIP 内的 `homepage` 是展示网站，`uploader.json` 中 `upload.url` 才是实际请求地址；登记文件的 `approvedPermissions.network` 应与 `uploader.json` 的 `permissions.network` 一致。

## 更新

在作者仓库发布带有新 ZIP 的 GitHub Release，插件 ID 保持不变，版本按 SemVer 增加。目录计划每小时检查一次；通过验证后自动更新。不要修改已发布版本的附件。

若新版本增加或改变网络目标、不安全 HTTP 或云端删除权限，自动更新会停止。请先对登记文件中的 `approvedPermissions` 提交 PR，说明变化并等待审核。Picora 用户安装更新时仍会看到插件的实际权限。

## 退出收录

开发者可以随时申请移除自己的插件，退出理由可选。删除 `registrations/<插件 ID>.json` 并提交 PR，注明“退出收录”及插件 ID；不便提交 PR 时，可以[发起 Issue](https://github.com/Alnitak44/picora-plugins/issues/new)，附上插件 ID 和源码仓库链接。

维护者核实作者或获授权维护者的身份后处理。登记移除并成功生成新目录后，插件停止在线展示、下载和更新；客户端成功刷新目录后生效，缓存或镜像可能延迟。请勿直接修改自动生成的 `index.json` 或 README 插件列表。

退出收录不会卸载用户已安装的插件，也不会删除配置、上传记录或图床文件。作者自行管理源码仓库和 Release，已获取 ZIP 的用户仍可本地安装。需要恢复收录时，重新提交登记文件并接受审核。

## 常见问题

| 检查项 | 正确写法 |
| --- | --- |
| Release 附件名 | 推荐 `imgloc-1.1.0.picora-plugin.zip`；常见的重复 `.zip` 或 `.picora.plugin.zip` 会在 ZIP 校验通过后自动兼容并提示警告。仍不能使用草稿、预发布或自动生成的 Source code ZIP。 |
| 登记文件名 | `registrations/io.github.alnitak44.imgloc.json`；包含完整 ID 和 `.json` 后缀，与 ZIP 内的 `id` 一致。 |
| 网络权限 | `"network": ["imgloc.com"]`；填写主机名，不带 `https://` 或路径，与入口程序权限一致。 |
| 图标文字 `mark` | 可省略，默认 `P`；填写时使用 1–3 个字符，例如 `SB`。非法值会阻止收录，修改插件包后须递增版本重新发布。 |
| 源码地址 | `releaseRepository` 使用 `用户名/仓库名`；ZIP 内 `repository` 若填写，须使用同一仓库的 HTTPS 根 URL。未填写时目录自动从登记文件补出链接。 |
| 插件包结构 | `plugin.json`、入口 JSON、`readme.md` 和 `assets/` 直接位于 ZIP 根目录，不额外套目录。 |

失败时在 **Actions → Build plugin catalog → 失败的运行 → build** 查看失败步骤，查找 `catalog build failed: …`。修正作者 Release 后重新运行工作流；修正登记文件则提交新修改触发校验。不要手动修改生成目录。

更多报错、版本更新与缓存问题见[完整排查说明](https://github.com/Alnitak44/Picora/blob/main/docs/插件提交流程.md#常见问题与排查)。
