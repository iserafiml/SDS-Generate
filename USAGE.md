# SDS Generator — 使用说明

> 本工具用 AI 辅助生成 16 节 OSHA HCS 2012 格式的 SDS。**它产出的是高质量草稿，正式对外签发前必须由有资质的人复核。**

## 1. 启动

```bash
pip3 install -r requirements.txt          # 首次
python3 sds_app.py                        # 浏览器打开 http://localhost:5001
```

`config/api_config.json` 内需有有效 Anthropic key（`{"api_key":"sk-ant-..."}`）。
生成的 PDF 在 `output/`。目前仅本机可访问（局域网共享需另行开启）。

## 2. 生成一份 SDS（网页）

1. **公司**：在 Section 2 区选"Issuing company"和"24h Emergency contact"。没有就点 **Manage** 新建（可上传 logo）。
2. **产品信息**：填产品名、产品码等。
3. **材料**：每行一个搜索框，输 **RM# / CAS / 名称任意片段**（≥2 字）即联想，点选自动回填并标 In DB；库里没有的可手填 CAS 并点 **+ Hazards** 手选危害，或 **+ New material to library** 入库。填浓度上下限（按**到货规格%**，不是纯活性%）。
4. （可选）物化性质、NFPA/HMIS 覆盖、模糊配方勾选。
5. 点生成 → 进度条 → 下载 PDF。

## 3. 换公司重出同一份 SDS（零成本）

Section 2 区 **Re-issue** → 选一份已生成的 SDS + 另一家公司/紧急电话 → 重出。
**只换 Section 1 与 logo，不跑 AI，不花钱，秒出。**

## 4. 成本模型（用你自己的 Anthropic key 计费）

| 操作 | 是否花 API |
|---|---|
| 生成一份**全新** SDS（急救/消防/操作/物化估算等叙述） | 是，约几次调用 |
| 某化学品**首次**被富集（毒理/OEL/法规/危害） | 是，一次；之后**永久缓存**不再花 |
| 已富集化学品再用、GHS 分类、NFPA/HMIS、象形图、模糊配方 | 否 |
| **换公司重渲染已有 SDS** | **否（0）** |
| 材料搜索/下拉、公司管理、查阅下载 | 否 |
| 新增材料缺 CAS 查 PubChem | 否（免费公共接口，非 Anthropic） |

全库 ~171/175 化学品已**批量预富集并缓存**——日常生成时这部分不再产生费用。

## 5. ⚠️ 必看注意事项

- **AI 内容须复核**：Section 9 物化性质是**估算**（标 `(estimated)`）；富集的毒理/法规/危害分类是 best-effort。签发前请核对。
- **NFPA / HMIS** 是按 GHS 的**行业经验映射**，非官方定义；图下已注明，可在表单手动覆盖。
- **浓度填到货规格%**：如"Sodium Hydroxide 50%"投 20%，就填 20，不要填纯 NaOH 的 10%；系统对入库规格会自动按 `active_fraction` 折算纯物质再比 GHS 阈值。
- **GHS 浓度阈值**：低于切点的危害不会进 Section 2 属正确行为（例：钴 <0.1% 不计致癌，但加州 Prop 65 仍会在 Section 15 标示）。
- **模糊配方**只影响 Section 3 显示；危害分类与 8/11/12/15 始终用真实配方，**有危害组分不会被隐藏**。
- **专有混合物/染料香精**多无单一 CAS（约 14 个），需手动选危害。
- 改了代码或网页模板需**重启** `python3 sds_app.py`（无热重载）；只改数据 JSON 不用重启。

## 6. 维护脚本（一般不用动）

`batch_enrich.py` 全库预富集（可重跑补漏）·`add_material.py` 命令行加料·`build_rm_index.py`/`apply_cas_review.py` 等数据重建（读 `data/sources/`）。
