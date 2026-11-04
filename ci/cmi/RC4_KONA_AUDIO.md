# 小米 10 Pro（cmi）RC4 · ReSukiSU 音频兼容测试 AK3

版本：**1.0.0-rc4**。适用：国行 MIUI `V12.5.10.0.RJACNXM` / Android 11（SDK 30）。原有 RC3 用户反馈：相机与 Root 环境工作正常，播放音频没有声音。

**这是真正的 AnyKernel3 刷机 ZIP（不是模块、不是 APK），但音频修复未经实机验证。不能保证恢复声音或避免回归。** 建议先确保可进入 fastboot 且具备原 RC3 ZIP / boot 恢复途径，再考虑测试。

## 改动范围

1. 完整保留 RC3 Image 内 **22 字节旧 MIUI OIS 修正**，不触碰相机补丁。
2. 在 RC3 同一 Image 内 `0x014f7978`，将 `csel w23, w9, w8, ne` 改为 `mov w23, w8`，仅修改 4 个字节。原有 `msm_asoc_machine_probe` 在 `devm_snd_soc_register_card()` 返回 `-EPROBE_DEFER (-517)` 且 `codec_reg_done` 为真时，把错误改为 `-EINVAL (-22)`。此次补丁保留 -517，允许组件依赖完成后重新探测。这是与成功编译的官方 4.19.113 实验修复**同一源逻辑**的二进制改动。
3. 未使用该实验版 4.19.113 Image：实际输出仍是原版 4.19.325 内核，原 ReSukiSU `v4.2.0-rc1-f1dd81dc`、SUSFS 和其他内核代码保持字节一致。
4. 不替换 DTB、DTBO、vendor、ramdisk、音频模块，不跳过模块 CRC，不关闭 SELinux。

这个修正只改善 Kona 声卡的延迟注册语义，**未证明你的手机声卡就是因此失效**。若设备树音频 overlay、Codec 依赖或原厂 `.ko` 的 ABI 仍有问题，RC4 可能继续无声。编译成功的实验 Image 不可直接替代 RC3。

## 安装及恢复

请在目标手机系统正常启动时，通过支持纯 AnyKernel3 的内核刷写入口选择本 ZIP。安装器要求 cmi、Android 11、指定 vendor 和指定 camera HAL 的完整 SHA-256；仅接受原 Image、指定 RC1／RC2、RC3、或同一 RC4，其他内核一律拒绝。

**建议从已知实机相机正常的 RC3 升级。** 安装器在真正写入 boot 前备份**完整 boot 分区**并回读校验，路径 `/sdcard/Download/CMI_CameraFix_Backup/CMI-XXXXXXXX/boot_original.img`；写入后再次读取 boot 比较 kernel 与非内核内容。只更新 boot 内的 kernel，原 boot 的 ramdisk / DTB 等保持，其他分区不动。安装器不会自行重启。

升级前请确认有电脑 fastboot 救援条件，保存原 RC3 ZIP 和本次生成的 boot 备份。如出现不开机、相机或 Root 回归，确认机型、分区、槽位后依照备份目录 `恢复说明.txt` 恢复本次完整 boot（若原本为 RC3，即回到 RC3）；**不可将别的手机的 boot 备份用于当前设备。**

## 核验与限制

- RC3 Image SHA-256：`7805151f6dade48f4ac9bc2a478f38e0e04a3c7ee05046f4471c97dc5ebdfe32`
- RC4 Image SHA-256：`f444ccc6e78425e65a207c97d2936209864638fe661f812a7aa148daead108fa`
- RC3→RC4 的 **4 个字节**地址 `0x14f7978..0x14f797b`；除该指令外 Image 逐字节一致。
- 机器码和源代码关系已通过 AArch64 反汇编复核（见 `evidence/kona-defer-rc4.json`）。
- `source/patch_kona_defer.py` 支持从字节完全匹配的 RC3 Image 重建本包 Image。
- 本次主机隔离测试仅证明脚本的防误刷、备份、写后核对流程，不代表真机开机、音频、相机、SUSFS 已验证。

参考：[小米官方 Kona ASoC 驱动源码](https://github.com/MiCode/vendor_qcom_opensource_audio-kernel/blob/cmi-r-oss/asoc/kona.c)，[实验内核成功编译记录](https://github.com/Andyxyc/xm-ws/actions/runs/41581837302)，[前版 RC3 OIS 来源](source/README-RC3.md)。

归属：内核、ReSukiSU、SUSFS、AnyKernel3 与工具保留原作者及原许可。二进制最小修正和打包交付：闲鱼 心中都是莫。请保留 LICENSE、LICENSE-new.txt。