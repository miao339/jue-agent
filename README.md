# Jue-Agent（觉）

基于 Hermes Agent fork，用心学判断力理念重构的 AI agent 框架。

Jue-Agent 保留 Hermes Agent 的工具、技能、网关和终端体验基础，在其上加入判断力架构：不仅让 agent 学会“怎么做”，也让它积累“为什么这么做”。

> Documentation: TODO

## 核心区别

Hermes 积累做法（skill）。

Jue 积累为什么这么做（JudgmentTriplet，判断三元组）。

有判断过程的系统遇到新情境可以类推，只有做法的系统不行。Jue 的目标不是把所有行为写成规则，而是在真实任务中沉淀可复用的判断结构，让 agent 在新场景里能看见意图、权衡边界、再决定行动。

## 三层结构

1. 代码级安全边界（不可越过）

   这是最底层的 guard。判断力失效时，代码边界仍然接住危险操作。

2. ROOT_PARADIGM + SOUL（判断力来源）

   ROOT_PARADIGM 规定 Jue 站在哪里，SOUL 提供心学判断力的来源：行动前先觉察意图，不以规则替代判断，不确定时默认保守。

3. JudgmentTriplet + Harness（垂直领域判断力积累）

   JudgmentTriplet 记录一次真实情境中的判断过程，Harness 从多次判断中提取稳定模式。随着任务积累，Jue 可以形成垂直领域的判断力。

## 安装

```bash
git clone https://github.com/miao339/jue-agent.git
cd jue-agent
./setup-jue.sh
jue
```

默认运行时目录是 `~/.jue/`，与 Hermes 的 `~/.hermes/` 隔离。

## 常用入口

```bash
jue            # 启动 TUI
jue --no-tui   # 使用经典 CLI
jue model      # 选择 provider/model
jue tools      # 查看和配置工具
jue skills     # 查看和管理 skills
jue gateway    # 启动消息网关
jue doctor     # 环境诊断
```

## Project Status

Jue-Agent is an early fork and research implementation. The public documentation is being rewritten for the Jue architecture.

Current focus:

- Runtime isolation under `~/.jue/`
- ROOT_PARADIGM + SOUL prompt injection
- JudgmentTriplet and Harness storage
- Skill compatibility with the Hermes Agent ecosystem
- TUI/CLI/gateway entry points for practical use

## Credit

Jue-Agent is based on Hermes Agent, licensed under MIT.

The judgment architecture, including ROOT_PARADIGM, SOUL, JudgmentTriplet, and Harness, is original work by River (Zuduo Wei).

## License

MIT — see [LICENSE](LICENSE).
