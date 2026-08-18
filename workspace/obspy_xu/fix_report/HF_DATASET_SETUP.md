# HuggingFace Dataset 文件存储配置指南

## 问题背景

HF Space Docker容器中生成的文件不会自动同步到Git仓库。为了让用户能够方便地下载生成的波形图、处理结果等文件，我们实现了自动上传到HF Dataset的功能。

## 解决方案：HF Dataset自动上传

生成的文件会自动上传到一个HF Dataset仓库，用户可以直接从Dataset页面下载。

## 配置步骤

### 1. 创建HF Dataset仓库

访问 https://huggingface.co/new-dataset 创建一个新的Dataset：

- **Repository name**: `obspy-outputs` (或你喜欢的名字)
- **License**: 选择合适的许可证（建议MIT或Apache 2.0）
- **Visibility**: Public (公开，免费)

创建后，你的Dataset仓库URL应该类似：
```
https://huggingface.co/datasets/你的用户名/obspy-outputs
```

### 2. 获取HuggingFace Token

1. 访问 https://huggingface.co/settings/tokens
2. 点击 "New token"
3. Token类型选择 **Write** (需要写入权限)
4. 给token起个名字，比如 `obspy-mcp-upload`
5. 复制生成的token（只会显示一次！）

### 3. 配置HF Space环境变量

1. 进入你的HF Space设置页面：
   ```
   https://huggingface.co/spaces/你的用户名/你的Space名称/settings
   ```

2. 找到 **Repository secrets** 部分

3. 添加两个secret：

   **Secret 1:**
   - Name: `HF_TOKEN`
   - Value: 粘贴你刚才复制的HuggingFace token

   **Secret 2:**
   - Name: `HF_DATASET_REPO`
   - Value: `你的用户名/obspy-outputs`

4. 保存后重启Space

## 使用方法

配置完成后，用户在Cursor中使用MCP服务时，AI agent会自动：

### 方式1：自动上传（推荐）

用户询问：
```
帮我绘制波形图并上传到Dataset
```

AI agent会自动：
1. 调用 `plot_waveform()` 生成图片
2. 调用 `upload_to_hf_dataset()` 上传文件
3. 返回下载链接给用户

### 方式2：手动上传

用户询问：
```
把刚才生成的 waveform.png 上传到Dataset
```

AI agent会调用：
```python
upload_to_hf_dataset(
    file_path="/app/obspy_mcp/mcp_output/output/waveform.png"
)
```

返回结果示例：
```json
{
  "success": true,
  "download_url": "https://huggingface.co/datasets/username/obspy-outputs/resolve/main/output/waveform.png",
  "viewer_url": "https://huggingface.co/datasets/username/obspy-outputs/viewer/...",
  "message": "File uploaded successfully"
}
```

## 文件组织结构

上传到Dataset的文件会按照以下结构组织：

```
obspy-outputs/
├── output/          # 处理结果文件
│   ├── waveform.png
│   ├── filtered.mseed
│   └── ...
├── plots/           # 可视化图片
│   ├── spectrogram.png
│   ├── beachball.png
│   └── ...
└── wave_data/       # 波形数据
    ├── IU.ANMO.00.BHZ.mseed
    └── ...
```

## 下载文件

用户可以通过以下方式下载：

1. **直接链接下载**（AI agent会提供）：
   ```
   https://huggingface.co/datasets/username/obspy-outputs/resolve/main/output/waveform.png
   ```

2. **Dataset页面浏览**：
   访问 `https://huggingface.co/datasets/username/obspy-outputs`
   在Files标签页浏览和下载所有文件

3. **使用huggingface_hub下载**（Python）：
   ```python
   from huggingface_hub import hf_hub_download

   file_path = hf_hub_download(
       repo_id="username/obspy-outputs",
       filename="output/waveform.png",
       repo_type="dataset"
   )
   ```
   
## 验证配置

配置完成后，在Cursor中测试：

```
帮我下载IU台网ANMO台站的波形数据，绘制波形图，并上传到Dataset
```

如果看到类似以下输出，说明配置成功：
```
✅ 文件已上传到 HuggingFace Dataset
📥 下载链接: https://huggingface.co/datasets/username/obspy-outputs/resolve/main/plots/waveform.png
```

## 支持

如有问题，请检查：
1. HF Space日志（Settings → Logs）
2. MCP工具调用结果中的error字段
3. Dataset仓库的commits记录
