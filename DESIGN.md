---
name: 知学
description: 校园工作台、可嵌入的学业支持业务页，以及知学原版的界面规范。
colors:
  campus-navy: "#203c72"
  campus-action: "#28569c"
  campus-link: "#215da4"
  campus-ink: "#23354c"
  campus-muted: "#55677b"
  campus-line: "#dce4ee"
  campus-light: "#f2f6fb"
  campus-pass: "#236644"
  campus-risk: "#963d2f"
  surface: "#ffffff"
  original-primary: "#205446"
  original-deep: "#173e34"
  original-accent: "#d6e7b5"
  original-canvas: "#fbfbf7"
  original-rail: "#f2f4eb"
  original-selected: "#dde8d4"
  original-line: "#dce1d4"
  original-focus-action: "#dfebcb"
  home-preview-ink: "#1d2c25"
  home-preview-muted: "#65756c"
  home-preview-line: "#e3e9e5"
  home-preview-canvas: "#f7f9f8"
  home-preview-selected: "#eaf3ee"
  home-preview-assistant: "#edf4ef"
  home-preview-assistant-text: "#526c5b"
  home-preview-task-outline: "#718b79"
typography:
  campus-body:
    fontFamily: '"Helvetica Neue", "PingFang SC", "Microsoft YaHei", Arial, sans-serif'
    fontSize: "14px"
    lineHeight: 1.55
  campus-title:
    fontSize: "19px"
    fontWeight: 650
    letterSpacing: "0"
  campus-section:
    fontSize: "15px"
    fontWeight: 650
    lineHeight: 1.5
  campus-table:
    fontSize: "13px"
    lineHeight: 1.45
  campus-metric:
    fontSize: "27px"
    fontWeight: 650
    lineHeight: 1.4
  original-body:
    fontFamily: '"Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", system-ui, sans-serif'
    fontSize: "14px"
    lineHeight: 1.55
  original-title:
    fontFamily: '"Source Han Serif SC", "Noto Serif CJK SC", "Songti SC", "SimSun", serif'
    fontSize: "clamp(32px, 3.1vw, 47px)"
    fontWeight: 700
    lineHeight: 1.24
    letterSpacing: "0"
  original-credit:
    fontFamily: 'Georgia, "Times New Roman", "Microsoft YaHei UI", serif'
    fontSize: "clamp(38px, 3.6vw, 58px)"
    fontWeight: 400
    lineHeight: 1.04
  home-preview-body:
    fontFamily: '"Inter", "Segoe UI", "PingFang SC", "Microsoft YaHei UI", sans-serif'
    fontSize: "14px"
  home-preview-title:
    fontFamily: '"Inter", "Segoe UI", "PingFang SC", "Microsoft YaHei UI", sans-serif'
    fontSize: "28px"
    fontWeight: 650
    lineHeight: 1.25
    letterSpacing: "-0.02em"
  home-preview-section:
    fontSize: "15px"
    fontWeight: 650
    lineHeight: 1.4
  home-preview-credit:
    fontSize: "35px"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.04em"
rounded:
  table: "2px"
  control: "3px"
  embedded-card: "4px"
  pane: "5px"
  original-control: "6px"
  original-card: "7px"
  original-focus: "11px"
  soft: "12px"
  home-preview-control: "7px"
  home-preview-course: "11px"
  home-preview-panel: "12px"
spacing:
  row: "8px"
  group: "12px"
  gutter: "20px"
  home-preview-column: "23px"
  home-preview-stack: "22px"
components:
  campus-button-primary:
    backgroundColor: "{colors.campus-action}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "5px 12px"
  campus-button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.campus-link}"
    rounded: "{rounded.control}"
    padding: "5px 12px"
  campus-link:
    textColor: "{colors.campus-link}"
    padding: "2px 0"
  campus-filter-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.campus-ink}"
    rounded: "{rounded.control}"
    padding: "4px 7px"
  campus-tabs:
    height: "44px"
  campus-role:
    textColor: "{colors.surface}"
    rounded: "{rounded.soft}"
    padding: "0 9px"
  campus-credit-strip:
    backgroundColor: "#f3f7fc"
    padding: "12px 0"
  campus-course-detail:
    backgroundColor: "#f1f5fa"
    padding: "9px 12px"
  original-button-primary:
    backgroundColor: "{colors.original-primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.original-control}"
    padding: "8px 13px"
  original-card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.original-card}"
  original-focus:
    backgroundColor: "{colors.original-primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.original-focus}"
    padding: "22px clamp(25px, 3vw, 48px)"
  home-preview-button-primary:
    backgroundColor: "{colors.original-primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.home-preview-control}"
    padding: "8px 12px"
  home-preview-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.home-preview-ink}"
    rounded: "{rounded.home-preview-panel}"
    padding: "19px 20px"
  home-preview-assistant:
    textColor: "{colors.home-preview-assistant-text}"
    padding: "10px 0 0"
---

# 知学界面规范

## Overview

**Creative North Star: "学业核对工作台"**

学生打开培养方案时，需要看清哪些学分已经计入、还差多少，并能查到每门课的修读记录。辅导员在同一业务系统内核对负责学生的情况。两个入口共用业务数据和权限，默认展示模拟记录。

校园版（`/campus`）以深蓝顶栏、服务页签和位置路径组织查询，白色业务页可以单独打开（`/module`）。知学原版（`/`）在浅灰绿导航旁保留一整块暖白阅读区，首页用深绿区域呈现当前最需要处理的事项。登录页将表单与书桌照片并置，进入工作台后以学业记录和图表为主。学校风格用于参赛原型，统一登录、实时教务数据和在学校平台内正式挂载均需获得校方授权。

2026-11-14 学生首页预览是上述原版规范的局部例外：用户直接选择 Attio 与 Udacity 两个实际参考，要求先看一版，未进行概念种子选择。`home-preview-*` 仅描述独立入口中学生的“我的学情”及其活动外壳；`web/independent.js` 的 `onView` 只在学生 `mine` 页启用 `.independent.home-preview`，切页或登录后退出。它使用白色侧栏、冷调浅色画布与无衬线文字，保留原版绿色主操作。随后按 B1 场景将预警依据、下学期条件试算和师生跟进置于学情画像之前，以紧凑课程记录替换课程封面。校园版、辅导员及其他独立业务页继续使用既有规范；该预览不代表全站改版已获接受或已部署。来源为 `web/student-home.css`、`web/student-home.js` 与 `web/index.html`；方向与参考记录见 `.impeccable/surfaces/web-student-home-js.md`。当前 B1 版核对记录位于 `../inspection/2026-11-14/b1-home`，`../inspection/2026-11-14/home-redesign` 保留为此前预览的历史基线。

**Key Characteristics:**
- 宿主管理已打开的服务和当前位置，业务页承载查询、结果与明细。
- 学分数字旁保留单位和计算口径，状态用文字说明。
- 校园版用细线划分连续表格，原版用深绿突出当前行动，以页签和分隔线组织其余记录。

## Colors

校园版的深蓝用于宿主顶栏，操作蓝用于主按钮，链接蓝用于路径和表内操作。正文用深墨蓝，注释、口径和单位用灰蓝。白底、淡蓝表头和细分隔线让读者能沿一行核对数字。

**The Status Text Rule.** 绿色和红褐色分别配合“已通过”和“未通过”，待核对项用中性色。

原版用暖白作工作区底色，浅灰绿作侧栏底色。当前菜单项使用较深的灰绿底和加粗文字。品牌主绿用于首页行动区与表单主按钮，行动区内的按钮改用浅绿底。书页标记沿用黄绿色。嵌入的共享组件在业务页内继承校园版的配色覆盖，原版入口使用自己的色板。

学生首页预览使用文首的 `home-preview-*` 中性色，白色侧栏和卡片以细线分隔；当前菜单有浅绿底与加粗文字。主按钮继续引用 `original-primary`，悬停继承 `original-deep`。助手操作现在位于白色预警面板底部，接入模式采用 `home-preview-assistant-text`；行动完成圆圈沿用 `home-preview-task-outline`。此前预览的 `home-preview-assistant` 浅绿底色保留为既有记录，当前首页不再使用该底色或独立助手卡片。这些局部约定不重定义其他路线的颜色。

## Typography

校园业务正文优先使用设备上的中文无衬线字。标题、分节、表格与学分数字分别使用文首的四个层级，表头和注释进一步收至 12px。原版的登录标题、页面标题与首页行动标题使用中文宋体，正文、菜单和控件使用中文无衬线字。首页的已计入学分、人数和累计绩点使用 Georgia 优先的数字字体，单位与说明保持较小字号。

**The Credit Units Rule.** 学分采用等宽数字，单位另用小号常规字。

学生首页预览的标题、正文与控件统一使用 `home-preview-body` 字体栈，桌面标题和卡片分节采用对应预览层级；学分主值保留等宽数字。窄屏主标题收至 25px，学分主值收至 34px。既有原版宋体标题与 Georgia 数字继续适用于其他独立页面。

## Layout

校园顶栏高 45px，下方是可横向滚动的服务页签和位置路径。业务内容居中，含两侧内距的最大宽度为 1170px。桌面分类表并列显示要求、已获、计入、剩余、在读与核对结果。

宽度不超过 700px 时，校园版收起顶部搜索，保留菜单。页签降至 37px，业务页两侧内距收至 10px。三项总量仍并排，分类列表常显“课程类别、计入学分、剩余学分”，点击一行可查其余字段。宽明细表在自己的容器内横向滚动。

原版桌面侧栏宽 216px，宽屏（1500px 起）增至 238px。首页行动与学分或人数并列。宽度不超过 960px 时，导航切为可用键盘操作的抽屉。不超过 700px 时，首页行动、学分和下方详情由上至下排列，宽表在表格容器内滚动，登录照片移至表单上方。

学生首页预览桌面侧栏为 218px，顶栏高 57px，内容最大宽度为 1448px。主列与 310px 帮扶列并排，列距采用 `home-preview-column`、行距采用 `home-preview-stack`；网格依次为“预警 / 帮扶”“下学期风险 / 帮扶”“画像 / 画像”，帮扶列包含辅导员跟进和个人行动，画像内再并列呈现成绩与培养方案学分。不超过 1150px 时帮扶列与画像内学分列收至 280px，行列距为 20px 与 18px；不超过 960px 时沿用导航抽屉；不超过 760px 时按 DOM 顺序单列呈现预警、下学期风险、辅导员跟进、个人行动、画像，间距为 18px。1600px 起两处辅列增至 330px，行列距为 24px 与 28px。具体覆盖见 `web/student-home.css` 的媒体查询。

## Elevation & Depth

校园宿主仅给白色内容区加浅阴影，展开菜单时使用较深阴影。学分条、表格和折叠分组依靠底色及 1px 边线分层。原版首页的列表以留白和细线分组，白色业务卡片和嵌入校园业务页的共享卡片均使用平面边框。

学生首页预览沿用平面分层：白色面板、预警等级与数据待核对提示通过底色及 1px 边框区分，预警内的助手操作以细线上分隔，不额外加入卡片阴影。

## Shapes

校园输入框和按钮采用小圆角，表格外框更方，宿主白色内容区略圆。顶部身份按钮使用胶囊轮廓。原版的表单主按钮与白色业务卡片使用小圆角，首页行动区圆角更大，窄屏时收至 8px。

学生首页预览的控件与信息面板分别采用 `home-preview-control` 与 `home-preview-panel` 圆角；行动完成控件和处置阶段标记保持圆形。课程使用细线分隔的记录行，原 `home-preview-course` 圆角仅保留为此前封面卡片的记录，当前首页不再使用。它们是首页的局部形状，不覆盖既有卡片与表单的圆角。

## Components

- **服务导航。** 选中页签同时使用浅色下划线和较粗文字，切换服务同步更新位置路径。嵌入时由宿主管理导航，直接打开已登录的业务页时显示紧凑的服务选择栏。
- **按钮与输入。** 主操作蓝底白字，次操作白底蓝字。正文链接在悬停时加下划线。查询字段有可见标签。键盘焦点在业务页用蓝色轮廓，在深色顶栏与页签区用白色轮廓。
- **学分与课程明细。** 三列总量在标签下显示数字、单位和计算口径。课程按类别和子类逐层展开，每门课显示名称、代码、性质、学分和修读状态。外语路线试算旁就地说明保存行为。
- **原版首页行动。** 学生先看到当前等级最高的有效预警，并可查看依据。没有有效预警时，依记录呈现待完成行动、历史记录核对或下学期规划。辅导员从服务端排在首位的跟进或复查事项直接打开“跟进与反馈”。学生首页并列显示计入培养要求的学分与分类缺口，辅导员首页显示需关注和在管学生人数。
- **学生首页预览的风险与选课。** `StudentHome.view()` 读取本人学情、`/api/my/plan` 与学情接口的 `/selection-risk` 报告；默认演示仍为模拟数据。首个面板突出等级最高的有效预警、触发规则和数据依据，并保留等级计数、全部预警入口与完整依据抽屉。没有有效预警时，明确区分记录未触发与数据覆盖待核对。下学期区域直接呈现服务端报告中的分类缺口、在读通过后的预计缺口与后续平均负荷，就地说明通过假设、剩余学期、数据覆盖、模拟开课来源及大三评估范围。优先课程最多呈现三条紧凑记录；“记录”通过 `IndependentUI.openCourseRecords` 筛选已有明细，“比较安排”通过 `CampusRisk.openCourse` 进入既有风险检查并计算该课选与暂不选的方案，过期导航或已更新的课程清单不继续执行。当前首页不引用课程封面，原图片文件留作此前预览的来源记录。
- **学生首页预览的跟进与行动。** 跟进面板对应明确的预警，读取该预警明细中的实际事件，展示负责老师、最近记录与约定复查日期；处置阶段只标记当前项，不推断此前阶段均已完成。记录与反馈进入既有跟进页签，个人学习行动沿用已有保存行为，完成行动不会自动关闭预警处置。选课风险、行动清单或事件明细的可选请求失败时，各区显示未载入和重新载入入口。下方画像保留成绩走势、已记录选课和培养方案学分；读屏工具可读取逐学期绩点说明，装饰进度条隐藏。行动按钮包含任务名，按钮和数据说明保留可见焦点，窄屏行动完成控件的点击区域为 44px；减少动态效果时内容立即可见，并停止平滑滚动。助手按当前配置显示接入模式，预警上下文继续进入已有工作流。
- **原版详情与台账。** 页签以加粗文字和绿色下划线标识当前项，支持方向键切换。预警分开呈现依据与跟进，学期规划分开呈现选课与核查提交。台账保留搜索，把更多筛选项放入可展开的“筛选条件”。学期绩点折线附各学期的数值说明，便于使用读屏工具核对。
- **选课依据与审核。** 采纳时的比较随方案保存，注明时间、计算条件与模拟开课来源。当前课程或培养路线变化时显示文字提示。独立版审核页以“方案与理由、课程与检查、审核记录”组织内容，意见表单在切换时保留输入。校园版以可展开明细呈现同一份依据。

## Do's and Don'ts

- **Do** 在“已获”“计入”“剩余”旁保留各自的字段名称，窄屏先保留计入与剩余两列。
- **Do** 在演示模式下保留模拟数据标识、记录范围和核对状态，让读者知道数值的适用范围。
- **Don't** 在嵌入的业务页重复绘制宿主顶栏、服务页签或原版侧栏。
- **Don't** 仅靠颜色表达课程通过、未通过或待核对。
