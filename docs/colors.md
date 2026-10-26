# 知学配色约定

所有组件和内联 SVG 共用 `web/theme.css` 中的颜色变量。该文件先于 `styles.css` 和 `workspace.css` 加载；后两份文件负责原有组件布局和样式，不再各自定义色值。

| 用途 | 变量 |
| --- | --- |
| 标题和主要数字 | `--color-ink` |
| 正文、输入内容 | `--color-text` |
| 辅助说明、表头、时间 | `--color-muted` |
| 页面、卡片、浅色分区 | `--color-canvas` / `--color-surface` / `--color-subtle` |
| 分隔线、输入框边框 | `--color-border` / `--color-border-strong` |
| 主要操作、链接 | `--color-primary` / `--color-primary-hover` |
| 浅色强调、导航选中背景 | `--color-primary-soft` / `--color-accent` |
| 深色背景上的文字 | `--color-on-primary` / `--color-on-primary-muted` |
| 轻微提示或成功状态 | `--color-success` / `--color-success-soft` |
| 一般预警、待处理提醒 | `--color-warning` / `--color-warning-soft` |
| 危急预警、操作错误 | `--color-danger` / `--color-danger-soft` |
| 补充信息 | `--color-info` / `--color-info-soft` |
| 分类图表的四个系列 | `--color-chart-1` 至 `--color-chart-4` |

正常状态使用中性底色；轻微、一般、危急标签保留对应文字。图表分类颜色表示不同类别，不表示风险等级。若图表直接展示风险等级，使用对应状态色。

颜色只在 `theme.css` 集中修改。新增组件请选已有变量；不要在页面样式或图表模板中重新填写接近的十六进制颜色。浏览器标签栏颜色和内嵌网站图标无法继承页面变量，修改主色时需同步检查 `index.html` 中的两处静态配置。

校验时同时查看白底、浅色底和深色导航上的文字，以及悬停、焦点、预警标签、弹窗和手机菜单。普通文字以 4.5:1 为对比度目标，大号文字以 3:1 为目标。颜色数量用于维护，不作为界面好坏的唯一标准。
