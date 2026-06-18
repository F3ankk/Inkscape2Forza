# Inkscape2Forza / Inkscape2Forza

基于 **Inkscape** 的《极限竞速：地平线 6》(Forza Horizon 6) 彩绘纹饰分组编辑方式。  
A workflow for editing Forza Horizon 6 vinyl groups using **Inkscape**.

本项目旨在绕过FH6笨拙的内置编辑器，使用更强大的桌面级编辑软件改善体验。利用 Inkscape，你可以像设计师一样进行高精度排版、临摹和图层管理，并注入到游戏存档中。  
This project aims to bypass FH6’s clumsy built‑in editor by enabling desktop‑grade editing. With Inkscape, you can design with precision, trace images, manage layers like a professional, and inject the result into the game save.

## 核心特性 / Key Features

* **精准复刻的素材库**：编辑模板内置了高度精确的符号库，包含了《极限竞速：地平线 6》中**全部 1400 种**基础几何元素。  
  **Accurate symbol library**: The template includes a precisely recreated symbol set containing **all 1400 base geometric shapes** from Forza Horizon 6.

* **完整的矢量编辑支持**：支持图形选择、着色、缩放、旋转、倾斜、透明度调整及图层层级排序，操作手感与Inkscape矢量设计操作几乎一致。  
  **Full vector editing support**: Select, color, scale, rotate, skew, adjust opacity, and reorder layers—almost identical to native Inkscape vector editing.

* **便于临摹**：支持直接在底层垫入高清 PNG/JPG 位图用于描边临摹，手绘痛车党必备。注入工具会自动过滤辅助图层。  
  **Easy tracing**: You can place high‑resolution PNG/JPG images underneath for tracing. The injector automatically ignores non‑symbol layers.

## 环境要求 / Requirements

* **所需软件**：[Inkscape](https://inkscape.org/)  
  **Required software**: [Inkscape](https://inkscape.org/)

* **版本建议**：推荐使用 **v1.4.4 或以上版本**  
  **Recommended version**: **v1.4.4 or later**

## 使用工作流指南 / Workflow Guide

### 1. 准备画布 / Prepare the Canvas

下载本项目提供的 [Inkscape SVG 模板文件](https://github.com/F3ankk/Inkscape2Forza/blob/main/inkscape_template.svg)并打开。模板默认画布为 `1920x1080`。你可以将其另存为你的工作副本。  
Download and open the [Inkscape SVG template file](https://github.com/F3ankk/Inkscape2Forza/blob/main/inkscape_template.svg) included in this project. The default canvas size is `1920x1080`. Save a working copy for your project.

### 2. 创作与编辑规范 / Editing Rules

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

    * **不要**对Inkscape内的图形进行组合。如果为了编辑方便一定要组合，请在导入前全选->解除组合。  
      Do **not** group shapes. If grouping is necessary for editing, ungroup everything before import.

**提示**：一切不符合规范的操作（或不属于预定符号库的元素）都会在最终导入时被忽略，虽然不一定会引发错误，但会造成视觉效果与游戏内不一致。  
**Note**: Any unsupported operation or non‑symbol element will be ignored during import, potentially causing mismatches in‑game.

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

3. 导入时，工具会自动将其识别为蒙版。  
   The importer will automatically recognize it as a mask.

**注：** 蒙版符号支持调整 `不透明度 (Opacity)` 以达到半透明的擦除效果。请勿使用其他未知图案填充符号，以免引发错误。  
**Note**: Mask symbols support opacity adjustments for semi‑transparent erasing. Do not use other pattern fills.

## 存档注入与游戏内刷新 / Save Injection & In‑Game Refresh

完成 Inkscape 内的编辑后，请按照以下步骤将涂装注入游戏存档：  
After finishing your design in Inkscape, follow these steps to inject it into the game save:

1. **游戏内占位准备**：打开 FH6 彩绘纹饰分组编辑器，新建一个分组，并**放置与你 SVG 文件中有效图层同等数量的默认圆形图层**。  
   **Prepare placeholders**: In FH6’s vinyl group editor, create a new group and add **the same number of default circles** as your SVG’s valid layers.

2. **保存占位符**：给它取一个简单易记的名字，并确保共享选项为**私密**。  
   **Save the placeholder**: Name it something simple and set sharing to **private**.

3. **定位存档目录**：运行导入工具，选择你的游戏存档根目录（通常为 `C:\XboxGames\GameSave`）。  
   **Locate save directory**: Run the importer and select your FH6 save root (usually `C:\XboxGames\GameSave`).

4. **运行注入**：加载 SVG，选择占位用的彩绘纹饰分组进行注入。  
   **Inject**: Load your SVG and inject it into the placeholder group.

5. **游戏内刷新（非常重要）**：注入成功后，回到游戏内，**打开该分组，将所有图层解组并重新保存**以刷新缓存与缩略图。  
   **Refresh in‑game (critical)**: After injection, open the group in FH6, **ungroup all layers and save again** to refresh cache and regenerate the thumbnail.

## 鸣谢 / Acknowledgements

本项目的灵感与底层资源结构解析，极大地受益于 [forza-painter-fh6](https://github.com/bvzrays/forza-painter-fh6) 项目。  
This project’s inspiration and resource structure analysis benefited greatly from the [forza-painter-fh6](https://github.com/bvzrays/forza-painter-fh6) project.

在此向原作者及开源社区表达最诚挚的感谢！  
Sincere thanks to the original author and the open‑source community.

## 免责声明 / Disclaimer

请仔细阅读以下条款，**使用本工具即代表您同意自行承担所有风险**：  
Please read the following carefully. **Using this tool means you accept all risks**:

1. **业余项目**：本项目属于业余探索，可能包含未知 Bug，更新随缘。  
   **Hobby project**: This is a hobby project and may contain unknown bugs; updates are not guaranteed.

2. **账号风险警告**：修改本地存档违反微软/Xbox/FH6 用户条款，可能导致账号封禁或设备封锁。作者不承担任何后果。  
   **Account risk warning**: Modifying local save files violates Microsoft/Xbox/FH6 ToS and may result in account suspension or hardware bans. The author assumes no responsibility.
