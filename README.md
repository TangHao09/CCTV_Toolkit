# CCTV_Toolkit

> 导入 TS 录像，自动识别其中的 **AV3A** 音轨，转码为 AC3 / EAC3 / AAC / PCM

![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-3776ab)
![License](https://img.shields.io/badge/license-LPGL2.1-green)

---
## 快速开始

### 方式一：直接使用 EXE（推荐）

1. 从 [Releases](../../releases) 下载 `AV3A_Converter.exe`
2. 双击运行（Windows 10 / 11）
3. 点击「添加 TS 文件」导入录像 → 选择转码格式 → 「开始转换」
4. 输出文件默认生成在源文件所在目录，同名文件自动加 `(1)`、`(2)` 后缀

> ⚠️ 程序首次启动时会把自己解压到所在目录下的临时文件夹（EXE 退出后自动清理），因此**请不要把 EXE 放在只读目录**（如 `C:\Program Files`）。

### 方式二：从源码运行

需要 Python 3.10+ 和带 AV3A 解码器的 ffmpeg。

```powershell
git clone https://github.com/<你的用户名>/<仓库名>.git
cd <仓库名>

pip install -r requirements.txt
python av3a2aac-ac3.pyw
```

源码模式下，程序会在以下位置查找 ffmpeg：

1. 脚本同级目录下的 `ffmpeg\` 子目录（若存在）
2. 源码顶部的 `DEFAULT_FFMPEG_DIR` 常量（默认 `C:\Users\13568\Downloads\ffmpeg-av3a`）

**请修改 `DEFAULT_FFMPEG_DIR` 为你自己的 ffmpeg 路径**，或把 ffmpeg 目录放到脚本同级。

## 自己打包 EXE

准备一个**含 AV3A 解码器**的 ffmpeg 目录（需包含 `ffmpeg.exe` 及其全部依赖 DLL），然后：

```powershell
.\build.ps1
# 或指定自己的 ffmpeg 目录与 Python：
.\build.ps1 -FfmpegDir "D:\tools\ffmpeg-av3a" -PythonPath "C:\Python312\python.exe"
```

产物：`dist\AV3A_Converter.exe`。

打包脚本会：
- 自动安装 `requirements.txt` 依赖
- 收集 ffmpeg 目录下所有文件（**排除 `ffplay.exe`**，可省约 22 MB）
- 使用 `--collect-all ttkbootstrap` 打包主题资源
- 使用 `--runtime-tmpdir .` 让单文件 EXE 在自身目录解压

## 关于 FFmpeg

本工具**不附带** FFmpeg 二进制。你需要自行准备一个 **包含 AV3A 解码器**的构建，例如：

- 带 `libarcdav3a`（AV3a decoder by ArcVideo）的定制构建
- 其它自带 AVS3-P3 解码支持的 FFmpeg 构建

可用以下命令验证你的构建是否支持：

```powershell
ffmpeg -decoders | findstr av3a
# 期望看到类似： A....D libarcdav3a    AV3a decoder by ArcVideo (codec av3a)
```

> 官方 ffmpeg.org 构建**不包含** AV3A 解码器，`-codecs` 列表中会显示 `av3a` 但没有 `D`（Decoding）标志。

FFmpeg 的使用需遵守其 LGPL/GPL 许可协议。

## 技术实现要点

| 模块 | 说明 |
|---|---|
| **探测** | 优先使用 `ffprobe -print_format json`；若构建不含 ffprobe，则解析 `ffmpeg -i` 的 stderr，提取 codec / 采样率 / 声道布局 / 码率 / 时长 |
| **声道布局解析** | 支持 `stereo`、`mono`、`5.1`、`5.1(side)`、`5.1.4`、`7.1.4`、`9.1.6` 等 `a.b.c` 结构（各段数字相加），以及 `FL+FR+FC+...` 显式列表 |
| **下混** | 通过 `-filter:a:N aresample=ochl=stereo\|5.1` **显式**把解码后的 PCM 下混为目标布局，再送入编码器。避免 AAC/AC3 编码器直接拒收 `5.1.4` 等布局 |
| **未知声道兜底** | 声道数解析失败（0）时，AAC 强制下混 2.0，AC3/E-AC3 强制下混 5.1 |
| **流复制** | `-map 0 -dn -sn -c:v copy`，非 AV3A 音轨 `-c:a:N copy` |
| **线程安全** | 探测与转码均在后台线程执行；所有 UI 更新经 `queue.Queue` 回主线程，避免 tkinter 跨线程崩溃 |
| **输出命名** | 自动避让同名文件与源文件本身，避免覆盖 |

### 生成的 FFmpeg 命令示例

AAC（5.1.4 源 → 2.0）：

```bash
ffmpeg -y -hide_banner -loglevel warning -stats \
  -i "录制.ts" -map 0 -dn -sn -c:v copy \
  -c:a:1 aac -b:a:1 192k -filter:a:1 aresample=ochl=stereo -ac:a:1 2 \
  -max_muxing_queue_size 9999 "录制_out.ts"
```

PCM（无损保留 10 声道，输出 MKV）：

```bash
ffmpeg -y -hide_banner -loglevel warning -stats \
  -i "录制.ts" -map 0 -dn -sn -c:v copy \
  -c:a:1 pcm_s16le \
  -max_muxing_queue_size 9999 "录制_out.mkv"
```

## 已知限制

- **无法生成 Dolby Atmos**：Atmos 需要使用 Dolby 私有的 JOC（Joint Object Coding）对象编码器，任何第三方 FFmpeg 构建都无法生成。市面上所谓「E-AC3 + Atmos」的转换实际只会输出普通 E-AC3，Atmos 解码器不会激活。
- **AC3 / E-AC3 上限为 5.1**：源为 5.1.4 时，4 个天空声道会被下混折入耳平声道，无法完整保留。若需完整保留 5.1.4，请选择 **PCM**。
- **PCM 体积很大**：10 声道 48kHz/16bit 约 3.2 Mbps，2 小时录像约 2.8 GB，仅适合作为保真备份。
- **仅支持 Windows**：UI 与打包脚本均面向 Windows。
- 仅处理 **TS 系封装**（`.ts` / `.m2ts` / `.mts` / `.trp`）作为输入。

## 项目结构

```
AV3A_Converter/
├── av3a2aac-ac3.pyw    # 主程序（单文件，含 UI + 转码逻辑）
├── build.ps1           # 一键打包脚本
├── requirements.txt    # Python 依赖
└── README.md
```

## 常见问题

**Q：日志显示「无AV3A音轨」，但录像确实有声音？**
A：说明该录像的音轨不是 AV3A 格式，或你的 ffmpeg 构建无法识别它。用 `ffmpeg -i 文件.ts` 查看音轨 codec 名确认。

## License

本项目代码采用 LGPL2.1 许可证。对FFmpeg采用动态链接，遵循其自身的 LGPL2.1 许可证。
