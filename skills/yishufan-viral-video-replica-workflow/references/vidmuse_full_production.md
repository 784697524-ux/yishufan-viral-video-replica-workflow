# VidMuse完整制作分支

只在用户明确要求生成完整视频、剪辑或导出时读取。仅要求素材包、提示词、分镜或AI表写入时不得进入本分支。

## 进入条件

- 新生产的`08_replica_contract.json`使用schema v5，`brief_alignment.production_scope=full_video`；v3/v4仅作legacy审计，不授予生产权限。
- `run_quality_gate.py --stage pre-generation`返回`decision=allow_generation`。
- 产品资产、风格锁、人物设定、故事板、动作关键帧、逐镜头运动链和目标模型已经由用户确认或有明确来源。
- `music_strategy.status`为`source_locked`或`user_confirmed`。音乐待选时先产出最多3个候选并暂停；不得先生成视频再随意铺音乐。

## 运行时与只读预检

先完整读取已安装的`vidmuse`技能及其`references/command-map.md`，只使用其中存在的命令。确认运行时后执行只读检查：

```bash
vidmuse --version
vidmuse profile get --output json
vidmuse plan get --output json
vidmuse model list --video --output json
```

从实时结果核对目标模型的准确`model_name`、支持的参考模式、分辨率、时长和参数。用户锁定`seedance-2.5`时必须精确命中该名称；不可用就停止，不自动切换Hailuo、Kling、旧版Seedance或其他模型。

如果当前模型/账户输出不能给出可靠价格，不得编造积分估算。报告可确认的余额、已知单次成本和未知项，在第一次付费生成前停止等待用户决定。

若`profile get`返回认证错误，按照VidMuse技能要求让用户完成登录。不得输出token、cookie或完整配置。

## 预算和音乐

把合同中的每个Clip/Pxx转换为任务表：镜头、生成模式、输入资产、时长、分辨率、主要人物动作、产品动作、环境事件、主要运镜、起止状态、交接锚点、模型和预计积分。复杂动作镜头预留一次定向重生额度，总预算含该额度；余额不足时在任何视频生成前停止。

已确认音乐先运行：

```bash
vidmuse tool run analyze_music --param '{"audio_path":"<本地音乐路径>"}'
```

把真实开场冲击点、主要重拍、加速、Drop/高潮和品牌落版节拍回填运动计划。不得用想象的节拍代替分析结果。

## 同一Thread内执行

用户的完整制作请求授权创建项目、发送生成消息并消耗已预算的积分，但不授权切换模型、扩大预算或发布到社交平台。

使用`vidmuse thread create`创建一个Thread，上传已锁定的产品图、人物图、场景图、动作关键帧和音乐，并用重复的`--default-model key=value`锁定本次合同要求的所有视频默认模型。后续始终使用同一Thread：

```bash
vidmuse thread status <threadId>
vidmuse message list --thread <threadId> --last 5
vidmuse message send --thread <threadId> --text "<本轮明确任务>" --file <必要资产>
vidmuse asset list --thread <threadId> --output json
vidmuse asset generation-params --thread <threadId> --file-path <生成视频路径> --output json
```

每轮只推进一个可验收阶段：参考资产→故事板→动态镜头→镜头选择→时间线→导出。Thread要求确认资产或版本时，按合同判断并继续；不得重新改变已确认创意。

## 动态镜头质检与重生

每个候选镜头必须完整播放，并结合连续检查帧核对：

- 人物动作、脸手、服装与身体比例；
- 产品外形、比例、颜色、材质、结构、Logo及人物接触关系；
- 环境是否由人物/产品动作触发真实变化；
- 地平线、透视、视差、空间轴线与摄影机轨迹；
- 与前后镜头的方向、速度、姿势、构图和交接锚点；
- 音乐重拍、动作爆点与转场；
- 生成参数中的实际模型是否等于合同锁定模型。

以下均为不合格：只看首尾帧或缩略图、静态图推拉/Ken Burns、数字缩放/抖动伪装动态、快速切换掩盖静态、关键帧直接进入时间线、产品或场景参考图补时长。

问题镜头保留合格版本，只改一个主要变量后定向重生；默认一次，仍失败最多再试一次。连续两次失败就停止并报告镜头、失败现象、已改变量、已消耗积分和剩余积分，不能无限重试。

## 时间线、导出和证据回填

进入时间线前必须满足：全部计划场景和动态事件已生成；所有正式镜头来自锁定模型；逐镜头质检通过；音乐已分析；没有静态补片。

优先使用动作匹配、方向匹配、遮挡、构图匹配和音乐重拍硬切。原始镜头存在运镜、变形或连续性问题时返回生成阶段，不能用后期缩放、旋转、抖动或加速掩盖。

CLI当前通过Thread消息推动远程时间线与导出；不得仅因Thread存在就假定项目一定支持这些操作。如果最新Thread状态/消息不能确认时间线或最终导出能力，立即停止并返回项目ID、项目链接、已完成阶段、未完成操作和准确原因。除非用户另行授权，不得自动改用本地`vidmuse render`或其他工具拼片冒充VidMuse导出。

把最终入选镜头按合同顺序写入`09_delivery_manifest.json`，真实ASR写入`10_asr_manifest.json`，完整播放和连续帧证据写入`11_director_qc.json`，每个资产的实际模型/参数和重生记录另存`15_vidmuse_execution.json`。只有`pre-stitch=allow_stitch`才进入最终剪辑。

导出后下载MP4，对最终文件重新运行`prepare_reference.py`和`pre-publish`门禁。技术解码、黑帧检查或Thread显示“完成”都不等于可发布；仍须完整播放、双模型ASR、导演证据、产品/人物连续性、音画卡点和人工听音通过。发布到平台需要用户另行明确授权。
