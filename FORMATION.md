# 自定义布阵与单位 AI

主窗口的“自定义布阵（5 / 5 / 3）”打开阵型编辑器。三排分别有 5、5、3 个选择框，每格可选空位或已注册 AI 的单位，目前支持重机枪手。第三排显示在中间三个位置，其界面格号 1、2、3 对应棋盘列 2、3、4。

保存后，“按已保存阵型布阵并开战”和感染者全自动清理使用该阵型。至少配置一个单位，只部署所选 AI 单位。恢复原阵型为第一排第二、第四格的两名机枪手。第二排第二格可正常配置单位。配置保存在 `config/formation.json`，每次成功开战时另存实际阵型到 `artifacts/runtime/combat/active-formation.json`，战斗读取实际阵型而非编辑器的新草稿。旧配置中的经验飞机选项会被忽略。

PVP 保留一名机枪手加六个宝宝的送分阵容，开局机枪手操作复用同一个单位 AI 模块。

`unit_ai/heavy_gunner.py` 包含机枪手的部署图标、人物识别接口、技能顺序、技能按钮、命中评估、目标选择、瞄准及确认位置策略。保持一技能优先，二技能按列剩余血量排序并瞄准列前方目标，忽略对空三技能。`combat.py` 负责共同的画面识别、输入、回合等待及异常恢复，并为每个配置单位调用相应 AI。

新增 AI 时，在 `unit_ai` 目录定义控制器并添加到 `unit_ai/__init__.py` 的 `REGISTRY`。控制器需提供 `id`、`name`、`icon_template`、`skill_order`、`skill_points`、`drag_skills`、`aim_settle_seconds`，以及 `present`、`cooldown`、`targets`、`hits`、`evaluate`、`confirmation_target`、`locate_aim` 方法。注册后编辑器自动展示其名称；独特的技能机制需由对应控制器实现。

本次按要求只实现代码，未运行自动测试、GUI 验证或游戏实测。
