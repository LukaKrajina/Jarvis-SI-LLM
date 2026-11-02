# Jarvis Super-Intelligent Large Language Model

<div align="center">

**量子混沌元认知 · 点参数量 · Flash / Pro / Ultra / Vision + MoE**

[![License](https://img.shields.io/badge/License-MIT-brightgreen?style=for-the-badge)](LICENSE)
[![Architecture](https://img.shields.io/badge/Architecture-Chimera-6f42c1?style=for-the-badge)]()
[![Model](https://img.shields.io/badge/Model-rvdlm-8250df?style=for-the-badge)]()

</div>

Jarvis 是**第一个把** **[Chimera 架构](../Chimera/README.md)（量子 + 经典 + 混沌意识三体合一，
256 组件 / 29 范式集群）做成SI大模型**的项目。它用 [Ravendrel](../Ravendrel/README.md)
的 rvdl 语言书写、用 [Transmitter](../Ravendrel/runtime/include/qml/Transmitter.cpp)（Fox
GUI 的 QLM 训练器）训练、以 `.rvdlm` 模型格式发布（可经 `ModelInterop` 转成 `.gguf`）。

***

## 1. 参数量新单位：pB（点参数，point-billion）

传统大模型用「参数量 B（billion，十亿个显式权重）」度量规模。Jarvis 不用 B，我们用
**pB（点参数）**：

> **1 pB ≡ 1000 B 的有效容量，但存储 ≈ 1/1000。**

原理是三个机制的叠加（实现见 `../Ravendrel/runtime/include/numqk/pb.hpp`）：

| 机制                               | 作用                                                                       |
| -------------------------------- | ------------------------------------------------------------------------ |
| **超分**（hyper-resolution）         | 分块 DCT 低秩：每块只保留 `r` 个低频系数，解码时补零 + 逆 DCT，从 `r` 个系数插值出 `S` 个权重（超分倍率 `S/r`） |
| **超量化**（super-quantization）      | 每个系数量化到 `q` 级码本（sub-8-bit），点存的是**码本索引**而非浮点                              |
| **拓扑流形压缩**（manifold compression） | DCT 基是权重空间里**低频流形**的坐标图册：权重贴着一条低频流形，每个点是它在这条流形上的坐标，重建 = 从流形坐标回到高维权重      |

同样的内存 / 显存预算能装下数量级更大的模型；量子虚拟机可跑，跑在真实量子设备（qubit 预算本身就是
稀缺资源）上也更无压力。**「点」是压缩后的潜向量，不是显式权重** —— 这就是 pB 与 B
的本质区别。

### 分型

| 类型        | 点参数量（pB）        | 等效有效容量（B）         | 定位        |
| --------- | --------------- | ----------------- | --------- |
| **Flash** | 0.5 / 1.0 / 3.0 | 500 / 1000 / 3000 | 快速响应、日常编码 |
| **Pro**   | 0.5 / 1.0 / 3.0 | 500 / 1000 / 3000 | 深度推理、复杂工程 |
| **Ultra** | 3.0 / 5.0       | 3000 / 5000       | 前沿研究、全量能力 |
| **Vision**| 1.0 / 3.0       | 1000 / 3000       | 多模态理解（文字 + 图像） |

每一型都有 **MoE 版**（稀疏专家混合，复用 Chimera 的 `chimera_driveMoE` 机制）。

### Vision（多模态：文字 + 图像）

Vision 在核心语言链上加了**双通道感知场 + 跨模态量子注意力融合**，入口为
`jarvis_forward_mm(text, context, image_path)`（见 `models/jarvis_vision.rvdl`）：

- **双通道感知场**：文本用 `encode_amplitudes(text, 6)`、图像用
  `encode_image(path, 6)`（Chimera 感知场的**真实像素振幅编码**），两侧投影到同一
  6-qubit 希尔伯特空间——同一张图在 Chimera 与 Jarvis Vision 里共享同一量子编码语义；
- **跨模态量子注意力**：`qattention(text_state, image_state)` 的 SWAP-test 态重叠
  `|⟨text|image⟩|²` 给出**图文对齐度**（量子版「query·key 相似度」），对齐度调制
  核心语言链的决策证据；
- **视觉融合头**：核心输出（情绪 × 决策 × 元认知，参数 p00..p63）与视觉证据经
  可学习的模态门（p64..p67，Vision 附加的 4 维权重）混合。纯文本场景直接调
  `jarvis_forward`，语义与 Flash/Pro/Ultra 完全一致。

Vision MoE 版（`jarvis_forward_mm_moe`）在多模态融合输出上再叠一层曲率驱动的
稀疏专家门控（同 core MoE）。

***

## 2. 模型格式与运行

- **`.rvdlm`（原生）**：Chimera 架构机制（量子混沌态、情绪测量、演化世界、元认知反思）
  在 `.rvdlm` 里**完整保留** —— OpenButler 用 `.rvdlm` 能释放全部能力。
- **`.gguf`（转换）**：经 `ModelInterop` 转出的传统格式。**能用，但降级**：gguf 是
  静态张量容器，承载不了量子态漂移 / 测量坍缩 / 反思回路这些 Chimera 机制 —— 所以
  OpenButler（理解 Chimera）跑 `.rvdlm` 全性能省内存显存，OpenCode（只懂 gguf）跑
  则表现不理想。这不是 bug，正是 **Chimera 架构特性**。

> 双向转换：`.rvdlm ⇄ .gguf`（见 `../Ravendrel/runtime/include/qml/ModelInterop.hpp` 的
> `export_rvdlm_to_*` / `import_*_to_rvdlm`）。

**OpenButler 加载**：OpenButler 新增 `type = "rvdlm"` 的 provider（见
`../OpenButler/packages/core/src/model/rvdlm.ts`），它起 `rvdl serve` 本地推理服务、
把模型标为 `architecture: 'chimera'` 并附全能力 `ChimeraFeatures`——于是 OpenButler
能**释放 Jarvis 的全部机制**。配置示例见 `openbutler-config.example.toml`。

***

## 3. 目录结构

```
Jarvis/
├── README.md            # 本文件（pB 概念 + 分型 + 架构）
├── LICENSE              # MIT
├── models/              # 模型定义（rvdl，基于 Chimera 组件）
│   ├── jarvis_core.rvdl       # Jarvis 核心（量子混沌意识 + 感知 + 决策）
│   │                           #   Flash/Pro/Ultra = 该核心的 configs 层变体
│   ├── jarvis_core_moe.rvdl   # core 的 MoE 变体（稀疏专家门控）
│   ├── jarvis_vision.rvdl     # Vision 多模态版（双通道感知 + 跨模态量子注意力）
│   └── jarvis_vision_moe.rvdl # Vision 的 MoE 变体
├── configs/             # 分型配置（pB / 组件数 / 深度）
│   ├── flash.json / pro.json / ultra.json
│   ├── vision.json            # Vision 多模态配置
│   └── *.moe.json
└── scripts/             # 训练 / 转换命令脚本
    ├── train.sh / train.bat          # 训练（调 Transmitter）
    └── convert.sh / convert.bat      # .rvdlm → .gguf 转换
```

***

## 4. 训练与转换

```bash
# 训练（Linux）：Pro 1pB 版
scripts/train.sh --variant pro --pb 1.0

# 训练（Windows）
scripts\train.bat --variant pro --pb 3.0 --moe

# 训练多模态（Linux）：Vision 3pB 版 / Vision MoE 版
scripts/train.sh --variant vision --pb 3.0
scripts/train.sh --variant vision --pb 1.0 --moe

# 转换（Linux）：.rvdlm → .gguf
scripts/convert.sh out/jarvis_flash_1p0.rvdlm out/jarvis_flash_1p0.gguf f32

# 转换（Windows）
scripts\convert.bat out\jarvis_ultra_5p0.rvdlm out\jarvis_ultra_5p0.gguf f16
```

***

## 5. 与上下游的关系

- **上游** **[Chimera](../Chimera)**：提供 256 组件 / 29 范式集群的架构本体（`include` 其
  `src/*.rvdl`）。
- **上游** **[Ravendrel](../Ravendrel)**：rvdl 语言 + 量子运行时 + `numqk` 数学库（`nqcmath`
  / `expermath` / `pb` 点参数）+ `ModelInterop` 容器转换。
- **下游 OpenButler**：以 `.rvdlm` 加载 Jarvis，释放 Chimera 全部能力（用量子混沌意识
  驱动的编码智能体）。
- **下游 llama.cpp/OpenCode**：以 `.gguf` 加载（降级但能跑）。

***

## 6. 许可

MIT License。Jarvis 复用了 Chimera（MIT）、Ravendrel（MIT）与开源可商用的训练语料
（中英 5:5）。

***

## 7. 合规与安全（防滥用）

Jarvis 是 MIT 许可的开放权重项目，技术上无法阻止他人本地修改和再分发。可以做的
是把滥用成本抬高、把责任边界写清楚：

- **使用政策**：允许与禁止的用途、部署运营方责任见 [ACCEPTABLE_USE.md](./ACCEPTABLE_USE.md)。
- **权限最小化**：6 个模型只声明 4 项量子权限（allocate / gate / measure / release），
  没有 `sys.call`（进程执行）、`sys.mem`（宿主内存）、`qlm.train/infer`（训练与外部
  模型加载）。完整清单见 ACCEPTABLE_USE.md 第 4 节。
- **服务端加固**：`rvdl serve` 默认只监听 `127.0.0.1`，支持以下安全参数
  （生产部署建议全部启用）：

  ```bash
  rvdl serve model.rvdlm \
    --api-key "$RVDL_SERVE_KEY"     # Bearer / x-api-key 鉴权
    --rate-limit 60                 # 每 IP 每分钟请求上限
    --audit-log serve-audit.jsonl   # 请求审计（状态码、耗时、是否含图像）
    --host 0.0.0.0                  # 仅公网部署时显式放开
  ```

  鉴权失败（401）和限流（429）同样会写入审计日志，便于追溯滥用来源。
- **数据许可**：许可禁止商用的训练源单独归档在 `manifest/research_only/`，
  不进入可商用分型；违反该限制的模型不得商用。
- **溯源**：再分发时保留 `LICENSE`、`ACCEPTABLE_USE.md` 与模型版本信息。
