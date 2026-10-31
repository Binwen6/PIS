# 研究画像（Research Profile）

> 首次运行时会被写入 Notion「🧭 研究画像」页面，之后以 Notion 页面为准，本文件只作兜底。

## 研究背景
研究背景是大语言模型的机制可解释性（mechanistic interpretability），以及脑机接口（BCI）相关研究，如 EEG 多模态解码。熟悉 Transformer 内部表征分析，对神经信号解码也有一手经验。

## 当前主线（最高优先级，相关就一定要推送）
改进基于大语言模型的智能体之间的信息传递机制：结合信息论与 Transformer 内部隐状态的动态信息加工，用于 LLM agent 间的分工协作，以及部分可观测（部分信息可见）的合作博弈任务。核心问题是：智能体如何在线（test-time）读取搭档智能体（paired agent）的 latent / hidden states，从而进行高效的意图推断。
- Latent communication / hidden-state communication：agent 之间直接交换 hidden states、KV cache、embedding、soft tokens，而非自然语言消息
- Multi-agent LLM 协作与分工：communication protocol、communication efficiency、role specialization、debate 与 collaboration
- 意图推断与心智理论：intent inference、Theory of Mind（ToM）、opponent / partner modeling、belief tracking
- 部分可观测合作博弈：Dec-POMDP、Hanabi、emergent communication、ad hoc teamwork、zero-shot coordination
- 信息论视角：mutual information、information bottleneck、rate-distortion、communication 的信息量与冗余、信息在层间的流动
- 读取/干预内部表征的技术：probing、activation steering、representation engineering、sparse autoencoders（SAE）、logit lens、activation patching、circuits
- Test-time 方法：test-time adaptation、在推理时读取或对齐其他模型的表征、cross-model representation alignment

## 背景方向（有实质进展时推送）
- 机制可解释性的新方法与重要发现（尤其涉及 agent 行为、规划、信念表征的）
- EEG / MEG / fMRI 多模态神经解码，brain-to-text，神经表征与 LLM 表征的对齐
- 脑机接口的新范式与数据集

## 延伸兴趣（重要工作推送）
- Yann LeCun 路线的 World Model：JEPA、V-JEPA、I-JEPA、基于预测的自监督表征、objective-driven AI
- 自由能原理（Free Energy Principle）与主动推断（Active Inference），及其与 LLM / agent 的结合
- 听觉重建：从脑信号（EEG / MEG / ECoG / fMRI）重建语音、音乐或声音，auditory decoding

## 不感兴趣（请降权）
- 纯 benchmark 刷分、只是换数据集的增量工作
- 与上述方向无关的 CV 检测/分割、推荐系统、纯工程部署
- 单纯 prompt engineering 的多智能体框架堆砌（除非对通信机制有实质分析）

## 关注的人 / 机构（出现即加分）
- Yann LeCun / Meta FAIR（JEPA 系列）、Karl Friston（自由能原理）
- Anthropic interpretability 团队、Chris Olah、Neel Nanda、Google DeepMind interpretability
- Jakob Foerster（多智能体、Hanabi、emergent communication）

## English keywords
latent communication, hidden state communication, multi-agent LLM, agent communication, intent inference, theory of mind, partner modeling, cooperative game, partial observability, Dec-POMDP, Hanabi, emergent communication, zero-shot coordination, information theory, mutual information, information bottleneck, rate-distortion, mechanistic interpretability, sparse autoencoder, activation steering, probing, representation engineering, test-time, KV cache sharing, EEG decoding, brain decoding, neural decoding, brain-computer interface, MEG, fMRI, world model, JEPA, free energy principle, active inference, auditory reconstruction, speech decoding
