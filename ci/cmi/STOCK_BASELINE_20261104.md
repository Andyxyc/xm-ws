# 小米10 Pro 原厂基线重建

目标设备：cmi，MIUI V12.5.10.0.RJACNXM，Android 11。

## 路线修订

停止以 RC3/RC4 的第三方 4.19.325 Image 为基础叠加二进制补丁。RC4 的四字节 Kona 修改只是未经实机验证的假说，不再纳入本分支。声卡未注册、铃声与振动异常、通话失败和开机循环不能仅凭去掉安装校验解释或解决。

采用对应版本的官方 boot/DTBO 作为未修改参考件；内核与硬件驱动从固定 MiCode cmi-r-oss 源码重编。不得把此前未经验证的 4.19.113 实验 Image 冒充已经接入 Root 的原厂镜像，也不得仅把第三方 Image 填回原厂 boot 就称为原厂内核。

## 版本与构建

- MiCode 内核：64b40409431988d060f7484369c8c2d7deca1bb3。
- ReSukiSU：f1dd81dc96d7f3f6691e6ac8b50fba9ae8a2f17c；与之前包内版本后缀对应。
- 复用已编译成功的官方音频/WLAN 源码组装及工具链，但删除实验性 Kona defer 补丁。
- 第一阶段：原厂镜像参考获取、官方源码与原版本 ReSukiSU manual hook 编译和链接核验。
- 第一阶段明确关闭 SUSFS/KPM，不是最终完整功能包。SUSFS 仍待独立适配与验证，不宣称保留其运行能力。
- 官方源码重编不等于与出厂二进制字节相同；原厂 vendor 模块 ABI、启动、声音、电话、振动、相机及 Root 功能仍待验证。

## 后续 AK3 安装要求

用户撤销了安装时强制持久化 boot 备份的要求。最终安装器不创建必须成功的 Download/备份目录，不把备份或回执目录失败作为中止条件。拆包重封装需要的临时工作文件不是持久化备份。

必要的机型、目标分区、镜像大小和真实写入失败处理仍保留，不向错误机型或空路径写入。不能将同一未验证内核改名后重发。最终交付仍为纯 AK3 ZIP，不是管理器 APK。

## 当前执行证据

构建入口：.github/workflows/cmi-stockboot-resukisu.yml。
GitHub Actions： https://github.com/Andyxyc/xm-ws/actions/runs/41805692093 。
提交：61b4844b6b91977982cc1baa918cbd4b158a62fd。
本地主机十项测试通过，包括 hooks 开关两种 C 编译路径及实际旧构建入口生成后的 shell 语法检查。GitHub 的上一份成功构建入口 fixture 不在仓库中，该单项测试在 CI 会标记 skipped；不会把 skipped 算作通过。

尚未生成可刷原厂基线 AK3，尚未进行任何手机写入或实机验证。仓库不包含用户日志、设备唯一标识或凭据。
