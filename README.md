# 小米 10 Pro 编译工作区

目标：cmi / 国行 MIUI V12.5.10.0.RJACNXM / Android 11。
作者：闲鱼 心中都是莫（xiaomo）。

本独立分支不修改默认分支或其他机型的工作流；不要将本分支整树合并回默认分支。

当前工作流只从公开上游取得固定的 Android Clang r377782c、32/64 位 binutils 及 cmi-r-oss 配套 WLAN/data 驱动源码，并运行 ARM64 编译链接探针。产物是后续编译所需的公开依赖，不是内核或 AK3。

已有 SukiSU 41023、SUSFS 1.5.5 和音频内建 v0.2 的自定义补丁未上传到这个分支。此工作流不包含聊天记录、设备附件或原厂提取的二进制。

仅使用 GitHub 标准 Ubuntu 运行器和只读仓库令牌，产物保留一天，不自动发布 Release。工具链来源与版本校验见脚本及每次运行产物中的 SOURCES.txt、SHA256SUMS。
