# Inkscape2Forza
<p align="center">
  <img src="https://github.com/F3ankk/Inkscape2Forza/blob/main/img/00.jpg" alt="show" width="720">
</p>

基于 **Inkscape** 的《极限竞速：地平线 6》(Forza Horizon 6) 彩绘纹饰分组编辑方式。  
A workflow for editing Forza Horizon 6 vinyl groups using **Inkscape**.

本项目旨在绕过FH6笨拙的内置编辑器，使用更强大的桌面级编辑软件改善体验。利用 Inkscape，你可以像设计师一样进行高精度排版、临摹和图层管理，并注入到游戏存档中。  
This project aims to bypass FH6’s clumsy built‑in editor by enabling desktop‑grade editing. With Inkscape, you can design with precision, trace images, manage layers like a professional, and inject the result into the game save.

## 核心特性 / Key Features

* **精准复刻的素材库**：编辑模板内置了高度精确的符号库，包含了《极限竞速：地平线 6》中**全部 1400 种**基础几何元素。  
  **Accurate symbol library**: The template includes a precisely recreated symbol set containing **all 1400 base geometric shapes** from Forza Horizon 6.

  **v0.1.0 更新**：1400 个 FH6 符号改为可安装的 Inkscape 用户符号库；工作 SVG 仅嵌入实际使用的符号和图案，因此保持轻量且可独立分发。  
  **v0.1.0 update**: The 1400 FH6 shapes are now installed as an Inkscape user symbol library. Working SVGs embed only the symbols and patterns they use, keeping them small and portable.  

* **彩绘纹饰分组导入/导出**：支持从 FH6 存档导出为可编辑 SVG。（仅支持导出自己创建的彩绘纹饰分组）  
  **Vinyl group import/export**: Export editable SVGs from FH6 saves. (Only supports exporting vinyl groups you created.)

* **完整的矢量编辑支持**：支持图形选择、着色、缩放、旋转、倾斜、透明度调整及图层层级排序，操作手感与Inkscape矢量设计操作几乎一致。  
  **Full vector editing support**: Select, color, scale, rotate, skew, adjust opacity, and reorder layers—almost identical to native Inkscape vector editing.

* **便于临摹**：支持直接在底层垫入高清 PNG/JPG 位图用于描边临摹，手绘痛车党必备。注入工具会自动过滤辅助图层。  
  **Easy tracing**: You can place high‑resolution PNG/JPG images underneath for tracing. The injector automatically ignores non‑symbol layers.

* **v1.0.0 正式版更新**：工具有了GUI界面。感谢群友YukiQWQ8492的适配工作。
  **v1.0.0 update**: the tool now has a GUI. Thanks to YukiQWQ8492 for the adaptation work.

## 环境要求 / Requirements

* **所需软件**：[Inkscape](https://inkscape.org/)  
  **Required software**: [Inkscape](https://inkscape.org/)

* **版本建议**：推荐使用 **v1.4.4 或以上版本**  
  **Recommended version**: **v1.4.4 or later**

## 启动工具 / Launch the Tool

请在release页面下载最新的 `Inkscape2Forza.exe`，双击运行即可。
Please download the latest `Inkscape2Forza.exe` from the release page and double-click to run.

## 使用工作流指南 / Workflow Guide

### 1. 准备画布 / Prepare the Canvas

~~下载本项目提供的 [Inkscape SVG 模板文件](https://github.com/F3ankk/Inkscape2Forza/blob/main/inkscape_template.svg) 并打开。模板默认画布为 `1920x1080`。你可以将其另存为你的工作副本。~~  
~~Download and open the [Inkscape SVG template file](https://github.com/F3ankk/Inkscape2Forza/blob/main/inkscape_template.svg) included in this project. The default canvas size is `1920x1080`. Save a working copy for your project.~~

**v1.0.0 更新**：先点击“安装FH6符号库到Inkscape”功能卡片。它会安装 `FH6_Vinyl_Symbols.svg` 与 `FH6_Vinyl_Patterns.svg` 到当前用户的 Inkscape 资源目录。之后可直接新建空白 Inkscape 文档，并在 **Symbols** 面板插入 FH6 图形。推荐设定画布尺寸为`1920x1080`。

**v1.0.0 update**: Click the “Install symbol library to Inkscape” action card first. It installs `FH6_Vinyl_Symbols.svg` and `FH6_Vinyl_Patterns.svg` into the current user's Inkscape resource directories. You can then create a blank Inkscape document and insert FH6 shapes from the **Symbols** panel. A `1920x1080` canvas size is recommended.

**在此之前请确保已安装了Inkscape 1.4.4 或以上版本并初次运行过！！否则安装器无法找到安装位置**
**Make sure you have installed Inkscape 1.4.4 or later and run it at least once before this step! Otherwise, the installer cannot find the installation path.**

其他画布尺寸也可以导入；工具会将画布内容等比例适配到 FH6 的 `1920x1080` 坐标空间。非 16:9、极端宽高比或画布外内容可能导致显示偏差、留边或图案过小。  
Other canvas sizes can also be imported. The tool fits the canvas uniformly into FH6's `1920x1080` coordinate space. Non-16:9 documents, extreme aspect ratios, or content outside the canvas may cause visible offsets, margins, or very small artwork.

### 更新 / Update

~~你现在可以直接使用工具内第一项功能生成空白模板~~，或使用 Geometrize JSON / Vinylizer JSON 生成模板。测试使用 [forza-painter geometrize GPU Version](https://github.com/zjl88858/forza-painter-geometrize-gpu) 和 [vinylizer](https://github.com/Heavenchaos/vinylizer) ，目前仅支持旋转椭圆 / 渐变柔边椭圆。  
~~You can now generate a blank template directly using the first feature in the tool,~~ or generate a template from a Geometrize JSON / Vinylizer JSON file. Tested with the [forza-painter geometrize GPU Version](https://github.com/zjl88858/forza-painter-geometrize-gpu) and [vinylizer](https://github.com/Heavenchaos/vinylizer), currently supports rotated ellipses / soft ellipses.

**v0.1.0 更新**：“安装 FH6 符号库”功能会将符号库安装到用户路径。符号不再内嵌在分发 SVG 中。

**v0.1.0 update**: The “Install symbol library” action installs the library to the user path. Symbols are no longer embedded in the distributed SVG.
<p align="center">
  <img src="https://github.com/F3ankk/Inkscape2Forza/blob/main/img/04.jpg" alt="template_generate" width="720">
</p>

~~(蓝月痴收收味)~~

### 2. 编辑规范 / Editing Rules

请打开 Inkscape 的 **符号库 (Symbols)** 面板来调出基础图形。  
Open the **Symbols** panel in Inkscape to access the base shapes.

* ✅ **支持的操作**：从符号库拖出图形，并对其进行着色、缩放、旋转、倾斜、复制、调整透明度及改变图层顺序。  
  **Allowed**: Drag symbols, recolor, scale, rotate, skew, duplicate, adjust opacity, and reorder layers.

* 🚫 **严禁的操作**：  
  **Forbidden actions**:

    * **不要**使用“路径工具”等改变符号本身拓扑形状的操作。  
      Do **not** modify symbol topology using path tools.

    * **不要**添加符号库中不存在的新矢量图形。  
      Do **not** add new vector shapes not included in the symbol library.

    * **不要**为符号填充无色或非蒙版纹理图案。  
      Do **not** apply arbitrary pattern fills or textures.

    * ~~**不要**对Inkscape内的图形进行组合。如果为了编辑方便一定要组合，请在导入前全选->解除组合。~~  
      ~~Do **not** group shapes. If grouping is necessary for editing, ungroup everything before import.~~

**提示**：一切不符合规范的操作（或不属于预定符号库的元素）都会在最终导入时被忽略，虽然不一定会引发错误，但会造成视觉效果与游戏内不一致。  
**Note**: Any unsupported operation or non‑symbol element will be ignored during import, potentially causing mismatches in‑game.

**v0.1.0 更新**：支持 Inkscape 的普通分组/组合；导入后也会保留为 FH6 分组。  
**v0.1.0 update**: Normal Inkscape groups are supported and are preserved as FH6 groups on import.

### 3. 使用辅助底图进行临摹 / Tracing with Reference Images

你可以将真实照片、ACG 图片或 Logo 的 PNG/JPG 文件拖入 Inkscape 作为底层参考图片。一切非符号库元素都会在导入时被忽略，不会写入游戏存档。  
You may drag PNG/JPG images (photos, comic art, logos) into Inkscape as reference layers. All non‑symbol elements are ignored during import and will not be written to the save file.

### 4. 关于蒙版图形 / About Mask Shapes

由于 FH6 的蒙版逻辑十分简单粗暴（使其下方所有图层被遮罩部分变透明，露出车漆），我们在 Inkscape 中采用了一种特殊的图案填充来标记蒙版：  
Because FH6 uses a very simple mask logic (masked areas reveal the car paint beneath), we use a special pattern fill in Inkscape to mark mask shapes:

1. 选中你要作为蒙版的图形。  
   Select the shape you want to use as a mask.

2. 将其填充修改为预设的 `mask_indicator_dark` 或 `mask_indicator_light` 图案（视你选择的画布背景主题而定）。  
   Change its fill to the preset `mask_indicator_dark` or `mask_indicator_light` pattern.
   <p align="center">
     <img src="https://github.com/F3ankk/Inkscape2Forza/blob/main/img/03.jpg" alt="mask_pattern" width="480">
   </p>
3. 导入时，工具会自动将其识别为蒙版。  
   The importer will automatically recognize it as a mask.

**注：** 蒙版符号支持调整 `不透明度 (Opacity)` 以达到半透明的擦除效果。请勿使用其他未知图案填充符号，以免引发错误。  
**Note**: Mask symbols support opacity adjustments for semi‑transparent erasing. Do not use other pattern fills.

**v0.1.0 更新**：从 JSON 生成和从 FH6 存档导出的 SVG，如包含蒙版，默认使用 `mask_indicator_dark`。  
**v0.1.0 update**: SVGs generated from JSON or exported from FH6 use `mask_indicator_dark` by default when they contain masks.

## 存档注入与游戏内刷新 / Save Injection & In‑Game Refresh

完成 Inkscape 内的编辑后，请按照以下步骤将涂装注入游戏存档：  
After finishing your design in Inkscape, follow these steps to inject it into the game save:

1. ~~**游戏内占位准备**：打开 FH6 彩绘纹饰分组编辑器，新建一个分组，并**放置与你 SVG 文件中有效图层同等数量的默认圆形图层**。~~  
   ~~**Prepare placeholders**: In FH6’s vinyl group editor, create a new group and add **the same number of default circles** as your SVG’s valid layers.~~

   **v0.1.0 更新**：打开 FH6 彩绘纹饰分组编辑器并新建或选择任意分组即可（FH6中一个分组最少需要包含2个图形）。待注入分组不再需要与 SVG 有效图层数相同的层数，占位图形也不再要求是白色圆形；任何颜色、任何图形、任何原有层数均可。  
   **v0.1.0 update**: Create or select any FH6 vinyl group (minimum 2 shapes required). The target group no longer needs the same number of layers as the SVG, and placeholders no longer need to be white circles; any color, shape, and existing layer count are accepted.
   <p align="center">
     <img src="https://github.com/F3ankk/Inkscape2Forza/blob/main/img/01.jpg" alt="placeholder_vinylgroup" width="480">
   </p>
2. **保存占位符**：给它取一个简单易记的名字，并确保共享选项为**私密**。  
   **Save the placeholder**: Name it something simple and set sharing to **private**.

3. ~~**定位存档目录**：运行导入工具，选择你的游戏存档根目录（通常为 `C:\XboxGames\GameSave`）。~~  
   ~~**Locate save directory**: Run the importer and select your FH6 save root (usually `C:\XboxGames\GameSave`).~~

   **v0.1.0 更新**：运行导入工具。工具会优先自动使用 `C:\XboxGames\GameSave`；目录不存在或无效时才要求手动选择。  
   **v0.1.0 update**: Run the importer. It first tries `C:\XboxGames\GameSave` automatically and asks for manual selection only when that directory is missing or invalid.

4. **运行注入**：加载 SVG，选择占位用的彩绘纹饰分组进行注入。  
   **Inject**: Load your SVG and inject it into the placeholder group.  

5. **游戏内刷新（非常重要）**：注入成功后，回到游戏内，**打开该分组，并重新覆盖保存**以刷新缓存与缩略图。  
   **Refresh in‑game (critical)**: After injection, open the group in FH6, **save it again** to refresh cache and regenerate the thumbnail.  

## 鸣谢 / Acknowledgements

本项目的灵感与底层资源结构解析，极大地受益于 [forza-painter-fh6](https://github.com/bvzrays/forza-painter-fh6) 项目。  
This project’s inspiration and resource structure analysis benefited greatly from the [forza-painter-fh6](https://github.com/bvzrays/forza-painter-fh6) project.

此外还要感谢 [forza-painter geometrize GPU Version](https://github.com/zjl88858/forza-painter-geometrize-gpu) 和 [vinylizer](https://github.com/Heavenchaos/vinylizer) 项目.
Special thanks also go to [forza-painter geometrize GPU Version](https://github.com/zjl88858/forza-painter-geometrize-gpu) and [vinylizer](https://github.com/Heavenchaos/vinylizer).

感谢群友 YukiQWQ8492 的GUI适配工作!

在此向原作者及开源社区表达最诚挚的感谢！  
Sincere thanks to the original author and the open‑source community.

## 免责声明 / Disclaimer

请仔细阅读以下条款，**使用本工具即代表您同意自行承担所有风险**：  
Please read the following carefully. **Using this tool means you accept all risks**:

1. **业余项目**：本项目属于业余探索，可能包含未知 Bug，更新随缘。  
   **Hobby project**: This is a hobby project and may contain unknown bugs; updates are not guaranteed.

2. **账号风险警告**：修改本地存档违反微软/Xbox/FH6 用户条款，可能导致账号封禁或设备封锁。作者不承担任何后果。  
   **Account risk warning**: Modifying local save files violates Microsoft/Xbox/FH6 ToS and may result in account suspension or hardware bans. The author assumes no responsibility.
