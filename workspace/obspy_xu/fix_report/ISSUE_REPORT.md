# code2mcp 工具问题反馈：ObsPy 转换案例分析

## 问题概述

code2mcp 工具在将 ObsPy GitHub 仓库转换为 MCP 服务时，**只暴露了约 30% 的核心功能**，导致生成的 MCP 服务与官方文档功能不匹配。

**源代码**: https://github.com/obspy/obspy
**官方教程**: https://docs.obspy.org/tutorial/

---

## 核心问题

### 1. **功能识别不完整**
code2mcp 生成的 `adapter.py` 已经包含了很多功能（约 20+ 方法），但 `mcp_service.py` **只暴露了 12 个 MCP 工具**，导致一些功能无法使用：

**adapter.py 中已实现但未暴露的功能：**
- ✅ `create_fdsn_client()` - FDSN 客户端（已实现）
- ✅ `apply_classic_sta_lta()` - STA/LTA 触发算法（已实现）
- ✅ `cross_correlate()` - 互相关（已实现）
- ✅ `plot_beachball()` - 震源机制绘图（已实现）
- ✅ `read_mseed()` - 读取 MiniSEED（已实现）
- ✅ `run_tests()` - CLI 工具（已实现）

**问题根源**：adapter.py 与 mcp_service.py **脱节**，中间层没有桥接。

### 2. **遗漏核心工作流功能**
根据 ObsPy 官方教程，以下核心功能完全缺失：

#### 2.1 数据读写与格式转换（最重要）
- ❌ `read()` - 读取波形数据（MiniSEED, SAC, SEGY 等）
- ❌ `stream.write()` - 写入多种格式
- ❌ `read_inventory()` - 读取台站元数据

#### 2.2 信号处理（核心功能）
- ❌ `stream.filter()` - 滤波（lowpass, highpass, bandpass）
- ❌ `stream.detrend()` - 去趋势
- ❌ `stream.resample()` - 重采样
- ❌ `stream.remove_response()` - 去仪器响应
- ❌ `stream.rotate()` - 坐标旋转

#### 2.3 FDSN 客户端（在线数据获取）
- ❌ `Client.get_waveforms()` - 下载波形
- ❌ `Client.get_stations()` - 获取台站信息
- ❌ `Client.get_events()` - 获取事件目录

#### 2.4 数据操作方法
- ❌ `stream.slice()` - 时间切片
- ❌ `stream.merge()` - 合并数据
- ❌ `stream.select()` - 选择特定通道
- ❌ `stream.trim()` - 裁剪

#### 2.5 可视化
- ❌ `stream.plot()` - 波形绘图
- ❌ `stream.spectrogram()` - 声谱图

#### 2.6 走时计算（TauP）
- ❌ `TauPyModel.get_travel_times()` - 计算相位到时
- ❌ `TauPyModel.get_ray_paths()` - 射线路径

### 3. **只关注对象创建，忽略核心方法**
生成的 MCP 工具主要是"create_xxx"类型：
- `create_stream` ✅
- `create_trace` ✅
- `create_catalog` ✅

但**缺少对这些对象的操作方法**：
- 创建 Stream 后如何滤波？❌
- 创建 Trace 后如何绘图？❌
- 创建 Catalog 后如何过滤事件？❌

**类比**：就像只提供了"新建文件"功能，却没有"编辑、保存、打开"功能。

---

## 人工修改内容

### 修改位置
仅修改 `mcp_output/mcp_plugin/mcp_service.py`，未改动 `source/` 源码。

### 新增功能分类

#### 1. 数据 I/O 功能
```python
@mcp.tool(name="read_waveform")
def read_waveform(file_path: str) -> dict:
    stream = read(file_path)
    # 返回 Stream 信息

@mcp.tool(name="write_waveform")
def write_waveform(file_path: str, format: str, ...) -> dict:
    stream.write(file_path, format=format)
```

#### 2. FDSN 客户端功能
```python
@mcp.tool(name="get_waveforms_from_fdsn")
def get_waveforms_from_fdsn(client_name: str, ...) -> dict:
    client = Client(client_name)
    stream = client.get_waveforms(...)

@mcp.tool(name="get_stations_from_fdsn")
@mcp.tool(name="get_events_from_fdsn")
```

#### 3. 信号处理功能
```python
@mcp.tool(name="filter_waveform")
def filter_waveform(file_path: str, filter_type: str, ...) -> dict:
    stream = read(file_path)
    stream.filter(filter_type, ...)

@mcp.tool(name="detrend_waveform")
@mcp.tool(name="resample_waveform")
@mcp.tool(name="remove_instrument_response")
```

#### 4. Stream/Trace 操作
```python
@mcp.tool(name="slice_waveform")
@mcp.tool(name="merge_waveforms")
@mcp.tool(name="select_traces")
@mcp.tool(name="trim_waveform")
```

#### 5. 可视化功能
```python
@mcp.tool(name="plot_waveform")
@mcp.tool(name="plot_spectrogram")
@mcp.tool(name="plot_beachball")
```

#### 6. 走时计算（TauP）
```python
@mcp.tool(name="calculate_travel_times")
def calculate_travel_times(source_depth_km: float, ...) -> dict:
    taup_model = TauPyModel(model=model)
    arrivals = taup_model.get_travel_times(...)

@mcp.tool(name="get_ray_paths")
```

#### 7. 触发算法和互相关
```python
@mcp.tool(name="apply_sta_lta_trigger")
def apply_sta_lta_trigger(file_path: str, ...) -> dict:
    cft = classic_sta_lta(trace.data, nsta, nlta)
    triggers = trigger_onset(cft, trigger_on, trigger_off)

@mcp.tool(name="cross_correlate_traces")
```

#### 8. CLI 工具和其他
```python
@mcp.tool(name="convert_flinn_engdahl")
@mcp.tool(name="rotate_to_zne")
```

---

## 建议改进方向

### 1. **增强 API 发现能力**
- 不要只关注 `__init__.py` 中的顶层导出
- **遍历核心模块的所有公开方法**：
  - `obspy.core.stream.Stream` 的所有方法
  - `obspy.core.trace.Trace` 的所有方法
  - `obspy.clients.fdsn.Client` 的所有方法
  - `obspy.signal.*` 中的信号处理函数

### 2. **参考官方文档/教程**
- 扫描 `docs/` 或 `README.md` 中提到的核心用法
- 识别 tutorial 中的常见工作流
- 优先暴露高频使用的 API

### 3. **adapter.py 与 mcp_service.py 联动**
- **当前问题**：adapter.py 实现了功能，但 mcp_service.py 没有调用
- **建议方案**：
  - 自动扫描 adapter.py 中的所有方法
  - 为每个方法自动生成对应的 `@mcp.tool`
  - 或者提示用户哪些 adapter 方法未被暴露

### 4. **区分"创建对象"与"操作对象"**
- 创建类：`create_stream`, `create_trace` ✅
- **操作类**（缺失）：
  - `filter_stream` - 滤波
  - `plot_stream` - 绘图
  - `merge_streams` - 合并
  - `slice_stream` - 切片

### 5. **支持链式调用工作流**
ObsPy 的典型工作流：
```python
# 1. 读取数据
stream = read("data.mseed")
# 2. 滤波
stream.filter('bandpass', freqmin=1.0, freqmax=5.0)
# 3. 去趋势
stream.detrend('linear')
# 4. 绘图
stream.plot()
```

code2mcp 最好能识别这种**链式操作模式**，而不是只提供孤立的创建函数。

---

## 效果对比

### 修改前（code2mcp 生成）
- ❌ 无法读取任何波形文件
- ❌ 无法从 FDSN 下载数据
- ❌ 无法进行任何信号处理
- ❌ 无法绘图或可视化
- ❌ 只能创建空对象，无实际用途

### 修改后（人工补充）
- ✅ 支持读写 10+ 种波形格式
- ✅ 支持从 IRIS/GEOFON/USGS 等数据中心抓数
- ✅ 支持完整的信号处理流程
- ✅ 支持波形/谱图/震源机制绘图
- ✅ 支持 STA/LTA 触发、互相关分析
- ✅ 支持走时计算（TauP 集成）

---

## 总结

code2mcp 工具在转换 ObsPy 时存在的核心问题：

1. **API 发现不充分**：只识别了基础类，忽略了核心方法
2. **adapter 与 service 脱节**：adapter.py 有功能但未暴露
3. **缺乏文档理解能力**：未参考官方 tutorial 识别高频 API
4. **只关注对象创建**：忽略了对象的操作方法
5. **工作流识别缺失**：未理解链式调用模式

建议：
- 增强对类方法的遍历和识别
- 增强 adapter.py 到 mcp_service.py 的自动桥接
- 参考项目文档/tutorial 进行智能 API 推荐
- 区分"创建"与"操作"等不同类型功能